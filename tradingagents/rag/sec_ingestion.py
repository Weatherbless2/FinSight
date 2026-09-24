"""R-14-B：批量下载 SEC 发现结果并保存可追溯原文。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from tradingagents.rag.documents import DocumentType, FinancialDocumentMetadata
from tradingagents.rag.ingestion import (
    DEFAULT_USER_AGENT,
    FetchedDocument,
    build_document_metadata,
    fetch_document,
    store_raw_document,
    write_failed_manifest,
)
from tradingagents.rag.sec_filings import SECFilingCandidate


class SECIngestionError(RuntimeError):
    """SEC 候选清单或批量导入参数无效。"""


@dataclass(frozen=True)
class ExistingDocument:
    """已落盘的成功文档，用于幂等跳过和版本冲突检测。"""

    document_id: str
    source_hash: str
    manifest_path: Path


@dataclass(frozen=True)
class SECIngestionSummary:
    """一批 SEC 导入的机器可读汇总。"""

    input_path: str
    output_dir: str
    as_of: str
    total_candidates: int
    stored_count: int
    skipped_count: int
    filtered_future_count: int
    failed_count: int
    items: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_path": self.input_path,
            "output_dir": self.output_dir,
            "as_of": self.as_of,
            "total_candidates": self.total_candidates,
            "stored_count": self.stored_count,
            "skipped_count": self.skipped_count,
            "filtered_future_count": self.filtered_future_count,
            "failed_count": self.failed_count,
            "items": list(self.items),
        }


Fetcher = Callable[..., FetchedDocument]


def load_sec_candidates(input_path: str | Path) -> tuple[SECFilingCandidate, ...]:
    """读取并校验 R-14-A 输出，防止未经校验的数据进入下载和文件系统。"""
    path = Path(input_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SECIngestionError(f"cannot read discovery JSON: {path}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("filings"), list):
        raise SECIngestionError("discovery JSON must contain a filings array")
    try:
        candidates = tuple(SECFilingCandidate.model_validate(item) for item in payload["filings"])
    except ValidationError as exc:
        raise SECIngestionError(f"invalid SEC candidate: {exc}") from exc
    return candidates


def _successful_manifests(output_dir: Path) -> dict[str, tuple[ExistingDocument, ...]]:
    """扫描成功清单；同一文档出现多个哈希时保留全部版本供上层报告冲突。"""
    by_document: dict[str, list[ExistingDocument]] = {}
    if not output_dir.exists():
        return {}
    for path in output_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            metadata = payload.get("metadata", {})
            if payload.get("status") != "succeeded":
                continue
            document_id = str(payload.get("document_id", ""))
            source_hash = str(payload.get("source_hash", ""))
            if not document_id or not source_hash or not isinstance(metadata, dict):
                continue
            by_document.setdefault(document_id, []).append(
                ExistingDocument(document_id, source_hash, path)
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            # 其他 JSON 不是成功清单时忽略，不能阻断整批导入。
            continue
    return {key: tuple(value) for key, value in by_document.items()}


def _metadata_for_candidate(
    fetched: FetchedDocument,
    candidate: SECFilingCandidate,
) -> FinancialDocumentMetadata:
    """把 SEC 字段映射为统一文档契约，日期语义保持明确。"""
    return build_document_metadata(
        fetched,
        document_id=candidate.document_id,
        ticker=candidate.ticker,
        document_type=cast(DocumentType, candidate.document_type),
        title=f"{candidate.company_name} {candidate.form} filing",
        published_at=candidate.filing_date,
        available_at=candidate.available_at,
        fiscal_period=candidate.fiscal_period,
        period_end=candidate.report_date,
        language="en",
    )


def ingest_sec_candidates(
    candidates: Iterable[SECFilingCandidate],
    *,
    output_dir: str | Path,
    as_of: date,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 20.0,
    max_bytes: int = 25 * 1024 * 1024,
    fetcher: Fetcher = fetch_document,
) -> SECIngestionSummary:
    """下载一批 SEC 候选；单条失败只影响当前条目，整批仍继续。"""
    candidate_items = tuple(candidates)
    root = Path(output_dir)
    existing = _successful_manifests(root)
    items: list[dict[str, Any]] = []
    stored_count = skipped_count = filtered_future_count = failed_count = 0

    for candidate in candidate_items:
        base = {"document_id": candidate.document_id, "source_url": candidate.source_url}
        if candidate.available_at > as_of or candidate.filing_date > as_of:
            filtered_future_count += 1
            items.append({**base, "status": "filtered_future"})
            continue

        versions = existing.get(candidate.document_id, ())
        hashes = {item.source_hash for item in versions}
        if len(hashes) > 1:
            error = SECIngestionError(
                f"multiple successful hashes for document_id={candidate.document_id}"
            )
            manifest = write_failed_manifest(
                source_url=candidate.source_url,
                output_dir=root,
                error=error,
                document_id=candidate.document_id,
            )
            failed_count += 1
            items.append({**base, "status": "failed", "error": str(error), "manifest": str(manifest)})
            continue
        if versions:
            skipped_count += 1
            items.append(
                {
                    **base,
                    "status": "skipped_existing",
                    "manifest": str(versions[0].manifest_path),
                }
            )
            continue

        try:
            fetched = fetcher(
                candidate.source_url,
                user_agent=user_agent,
                timeout=timeout,
                max_bytes=max_bytes,
            )
            metadata = _metadata_for_candidate(fetched, candidate)
            stored = store_raw_document(fetched, metadata, root)
        except Exception as exc:  # 每条文档独立失败，继续处理后续候选。
            manifest = write_failed_manifest(
                source_url=candidate.source_url,
                output_dir=root,
                error=exc,
                document_id=candidate.document_id,
            )
            failed_count += 1
            items.append({**base, "status": "failed", "error": str(exc), "manifest": str(manifest)})
            continue

        stored_count += 1
        existing.setdefault(candidate.document_id, ())
        existing[candidate.document_id] = (
            *existing[candidate.document_id],
            ExistingDocument(candidate.document_id, metadata.source_hash, stored.manifest_path),
        )
        items.append(
            {
                **base,
                "status": "stored",
                "raw_path": str(stored.raw_path),
                "manifest": str(stored.manifest_path),
                "source_hash": metadata.source_hash,
            }
        )

    return SECIngestionSummary(
        input_path="",
        output_dir=str(root),
        as_of=as_of.isoformat(),
        total_candidates=len(candidate_items),
        stored_count=stored_count,
        skipped_count=skipped_count,
        filtered_future_count=filtered_future_count,
        failed_count=failed_count,
        items=tuple(items),
    )


def ingest_sec_discovery_file(
    input_path: str | Path,
    *,
    output_dir: str | Path,
    as_of: date | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 20.0,
    max_bytes: int = 25 * 1024 * 1024,
    fetcher: Fetcher = fetch_document,
) -> SECIngestionSummary:
    """读取 R-14-A 文件并执行 R-14-B 下载。"""
    candidates = load_sec_candidates(input_path)
    if as_of is None:
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        as_of = date.fromisoformat(str(payload.get("as_of")))
    summary = ingest_sec_candidates(
        candidates,
        output_dir=output_dir,
        as_of=as_of,
        user_agent=user_agent,
        timeout=timeout,
        max_bytes=max_bytes,
        fetcher=fetcher,
    )
    return SECIngestionSummary(
        input_path=str(input_path),
        output_dir=summary.output_dir,
        as_of=summary.as_of,
        total_candidates=summary.total_candidates,
        stored_count=summary.stored_count,
        skipped_count=summary.skipped_count,
        filtered_future_count=summary.filtered_future_count,
        failed_count=summary.failed_count,
        items=summary.items,
    )
