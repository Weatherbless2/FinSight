"""R-14-A：从 SEC 官方接口发现公司财报和公告。

本模块只负责发现，不下载正文。它把 ticker 转换成 CIK，再读取 SEC
submissions 记录，输出后续下载工单可以直接消费的公开 HTML 地址。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import date
from typing import Any
from urllib.parse import quote

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tradingagents.dataflows.utils import safe_ticker_component

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DEFAULT_SEC_USER_AGENT = "TradeAgent/0.3 (local financial research; contact required)"

_SUPPORTED_FORMS = {
    "10-K": "annual_report",
    "10-K/A": "annual_report",
    "10-Q": "quarterly_report",
    "10-Q/A": "quarterly_report",
    "8-K": "announcement",
    "8-K/A": "announcement",
}


class SECDiscoveryError(RuntimeError):
    """SEC 元数据无法读取或返回内容不符合预期。"""


class SECCompany(BaseModel):
    """SEC ticker 映射中的公司身份。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str = Field(min_length=1, max_length=32)
    cik: int = Field(ge=1)
    company_name: str = Field(min_length=1, max_length=512)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return safe_ticker_component(value).upper()


class SECFilingCandidate(BaseModel):
    """一条可供 R-14-B 下载的 SEC 财报候选记录。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1, max_length=160)
    ticker: str = Field(min_length=1, max_length=32)
    cik: int = Field(ge=1)
    company_name: str = Field(min_length=1, max_length=512)
    form: str = Field(min_length=3, max_length=8)
    document_type: str = Field(min_length=1, max_length=32)
    accession_number: str = Field(min_length=18, max_length=24)
    filing_date: date
    report_date: date | None = None
    available_at: date
    fiscal_period: str | None = Field(default=None, max_length=32)
    primary_document: str = Field(min_length=1, max_length=512)
    source_url: str = Field(min_length=1, max_length=2048)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return safe_ticker_component(value).upper()


class SECClient:
    """带统一 User-Agent、超时和错误转换的 SEC JSON 客户端。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.session = session or requests.Session()
        self.user_agent = (
            user_agent or os.getenv("SEC_USER_AGENT") or DEFAULT_SEC_USER_AGENT
        )
        if not self.user_agent.strip():
            raise ValueError("user_agent must not be empty")
        self.timeout_seconds = timeout_seconds

    def get_json(self, url: str) -> Any:
        """请求一个 SEC JSON 接口，并把网络/格式错误转换为稳定异常。"""
        try:
            response = self.session.get(
                url,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SECDiscoveryError(f"SEC request failed: {url}: {exc}") from exc

    def find_company(self, ticker: str) -> SECCompany:
        """从 SEC ticker 映射中查找公司 CIK。"""
        normalized = safe_ticker_component(ticker).upper()
        payload = self.get_json(SEC_TICKERS_URL)
        if not isinstance(payload, dict):
            raise SECDiscoveryError("SEC ticker response must be an object")

        for item in payload.values():
            if not isinstance(item, dict):
                continue
            if str(item.get("ticker", "")).upper() != normalized:
                continue
            try:
                return SECCompany(
                    ticker=normalized,
                    cik=int(item["cik_str"]),
                    company_name=str(item["title"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SECDiscoveryError(
                    f"SEC ticker mapping is incomplete for {normalized}"
                ) from exc
        raise SECDiscoveryError(f"SEC company not found for ticker: {normalized}")

    def discover_filings(
        self,
        ticker: str,
        *,
        as_of: date | None = None,
        forms: Iterable[str] | None = None,
        limit_per_form: int | None = 5,
    ) -> tuple[SECFilingCandidate, ...]:
        """发现截至分析日已公开的 SEC 财报候选，并按新到旧排序。"""
        if limit_per_form is not None and limit_per_form < 1:
            raise ValueError("limit_per_form must be positive or None")
        cutoff = as_of or date.today()
        company = self.find_company(ticker)
        selected_forms = tuple(forms or _SUPPORTED_FORMS)
        invalid_forms = set(selected_forms) - set(_SUPPORTED_FORMS)
        if invalid_forms:
            raise ValueError(f"unsupported SEC forms: {sorted(invalid_forms)}")

        payload = self.get_json(SEC_SUBMISSIONS_URL.format(cik=company.cik))
        recent = payload.get("filings", {}).get("recent") if isinstance(payload, dict) else None
        if not isinstance(recent, dict):
            raise SECDiscoveryError("SEC submissions response has no filings.recent object")

        candidates: list[SECFilingCandidate] = []
        for row in _iter_recent_rows(recent):
            form = str(row.get("form", ""))
            if form not in selected_forms:
                continue
            filing_date = _parse_date(row.get("filingDate"), "filingDate")
            if filing_date > cutoff:
                continue
            primary_document = str(row.get("primaryDocument", "")).strip()
            accession = str(row.get("accessionNumber", "")).strip()
            if not primary_document or not accession:
                continue
            report_date = _parse_optional_date(row.get("reportDate"))
            document_id = _document_id(company.ticker, form, filing_date, accession)
            candidates.append(
                SECFilingCandidate(
                    document_id=document_id,
                    ticker=company.ticker,
                    cik=company.cik,
                    company_name=company.company_name,
                    form=form,
                    document_type=_SUPPORTED_FORMS[form],
                    accession_number=accession,
                    filing_date=filing_date,
                    report_date=report_date,
                    available_at=filing_date,
                    fiscal_period=_fiscal_period(row),
                    primary_document=primary_document,
                    source_url=_archive_url(company.cik, accession, primary_document),
                )
            )

        candidates.sort(key=lambda item: (item.filing_date, item.accession_number), reverse=True)
        if limit_per_form is None:
            return tuple(candidates)
        counts: dict[str, int] = {}
        limited: list[SECFilingCandidate] = []
        for candidate in candidates:
            count = counts.get(candidate.form, 0)
            if count >= limit_per_form:
                continue
            counts[candidate.form] = count + 1
            limited.append(candidate)
        return tuple(limited)


def _iter_recent_rows(recent: dict[str, Any]):
    """把 SEC 的按字段数组转换成按申报记录迭代，避免手写索引错位。"""
    forms = recent.get("form", [])
    if not isinstance(forms, list):
        raise SECDiscoveryError("SEC recent.form must be an array")
    for index in range(len(forms)):
        yield {key: values[index] for key, values in recent.items() if isinstance(values, list) and index < len(values)}


def _parse_date(value: Any, field_name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise SECDiscoveryError(f"SEC filing has invalid {field_name}: {value!r}") from exc


def _parse_optional_date(value: Any) -> date | None:
    if value in (None, "", "-"):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _fiscal_period(row: dict[str, Any]) -> str | None:
    fiscal_year = row.get("fy")
    fiscal_period = str(row.get("fp", "")).strip()
    if fiscal_year in (None, ""):
        return None
    return f"FY{fiscal_year}-{fiscal_period}" if fiscal_period else f"FY{fiscal_year}"


def _document_id(ticker: str, form: str, filing_date: date, accession: str) -> str:
    accession_slug = accession.replace("-", "")
    return f"sec-{ticker.lower()}-{form.lower().replace('/', '-')}-{filing_date}-{accession_slug}"


def _archive_url(cik: int, accession: str, primary_document: str) -> str:
    accession_slug = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_slug}/"
        f"{quote(primary_document, safe='') }"
    )
