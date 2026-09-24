"""R-10：基本面 Agent 的 API/RAG 路由和统一工具返回。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from tradingagents.dataflows.utils import safe_ticker_component

SearchSource = Literal["api", "rag", "api+rag", "none"]


class FinancialSearchResult(BaseModel):
    """API 和 RAG 对上层 Agent 暴露的统一结果格式。"""

    model_config = ConfigDict(extra="forbid")

    success: bool
    data: Any = None
    error_code: str | None = None
    retryable: bool = False
    source: SearchSource
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


ApiSearch = Callable[[str, str], Any]
RagSearch = Callable[[str, str, date], Any]


class FinancialSearchService:
    """根据问题类型选择结构化 API、RAG 或两者。"""

    _QUALITATIVE_TERMS = (
        "why",
        "risk",
        "outlook",
        "management",
        "guidance",
        "原因",
        "风险",
        "展望",
        "管理层",
        "公告",
        "表态",
    )
    _NUMERIC_TERMS = (
        "revenue",
        "margin",
        "eps",
        "cash flow",
        "income",
        "balance sheet",
        "营收",
        "利润",
        "现金流",
        "资产负债",
        "增长率",
    )

    def __init__(
        self,
        *,
        api_search: ApiSearch | None = None,
        rag_search: RagSearch | None = None,
    ) -> None:
        self.api_search = api_search
        self.rag_search = rag_search

    def choose_sources(self, query: str) -> tuple[Literal["api", "rag"], ...]:
        """把问题映射成数据源；混合问题按 API 后 RAG 的顺序执行。"""
        normalized = query.strip().lower()
        needs_rag = any(term in normalized for term in self._QUALITATIVE_TERMS)
        needs_api = any(term in normalized for term in self._NUMERIC_TERMS)
        if needs_rag and needs_api:
            return ("api", "rag")
        if needs_rag:
            return ("rag",)
        return ("api",)

    @staticmethod
    def _error(
        *,
        code: str,
        source: SearchSource,
        retryable: bool,
        message: str,
    ) -> FinancialSearchResult:
        return FinancialSearchResult(
            success=False,
            data={"message": message},
            error_code=code,
            retryable=retryable,
            source=source,
        )

    def search(self, *, query: str, ticker: str, curr_date: str) -> FinancialSearchResult:
        """执行路由并把成功、部分成功和失败统一成一个结果。"""
        normalized_query = query.strip()
        if not normalized_query:
            return self._error(
                code="INVALID_INPUT",
                source="none",
                retryable=False,
                message="query must not be empty",
            )
        try:
            normalized_ticker = safe_ticker_component(ticker).upper()
            as_of = date.fromisoformat(curr_date)
        except (TypeError, ValueError) as exc:
            return self._error(
                code="INVALID_INPUT",
                source="none",
                retryable=False,
                message=str(exc),
            )

        requested_sources = self.choose_sources(normalized_query)
        data: dict[str, Any] = {}
        errors: dict[str, str] = {}

        if "api" in requested_sources:
            if self.api_search is None:
                errors["api"] = "API search is not configured"
            else:
                try:
                    data["api"] = self.api_search(normalized_ticker, curr_date)
                except Exception as exc:  # noqa: BLE001 - 转成 Agent 可读的统一错误
                    errors["api"] = f"{type(exc).__name__}: {exc}"

        if "rag" in requested_sources:
            if self.rag_search is None:
                errors["rag"] = "RAG search is not configured"
            else:
                try:
                    data["rag"] = self.rag_search(normalized_query, normalized_ticker, as_of)
                except Exception as exc:  # noqa: BLE001 - 单次检索失败要可重试
                    errors["rag"] = f"{type(exc).__name__}: {exc}"

        source = "+".join(requested_sources)
        if data and errors:
            data["errors"] = errors
            return FinancialSearchResult(
                success=True,
                data=data,
                error_code="PARTIAL_SUCCESS",
                retryable=True,
                source=source,  # type: ignore[arg-type]
            )
        if data:
            return FinancialSearchResult(
                success=True,
                data=data,
                source=source,  # type: ignore[arg-type]
            )

        if requested_sources == ("rag",):
            # 没有后端和后端已配置但连接失败是两种不同问题，分别返回，
            # 这样 Agent/服务监控不会把数据库故障误判成配置遗漏。
            code = "RAG_NOT_CONFIGURED" if self.rag_search is None else "RAG_ERROR"
        else:
            code = "API_ERROR"
        if errors.get("api") == "API search is not configured":
            code = "API_NOT_CONFIGURED"
        return self._error(
            code=code,
            source=source,  # type: ignore[arg-type]
            retryable=code != "INVALID_INPUT",
            message="; ".join(errors.values()) or "search failed",
        )


def search_financial_documents(
    query: str,
    ticker: str,
    curr_date: str,
    *,
    service: FinancialSearchService,
) -> str:
    """执行基本面 API/RAG 路由，并返回 JSON 供 LangGraph ToolNode 回写。"""
    return service.search(query=query, ticker=ticker, curr_date=curr_date).model_dump_json()


def create_search_financial_documents_tool(
    service: FinancialSearchService,
):
    """创建绑定了具体服务实例的 LangChain 工具。"""

    @tool("search_financial_documents")
    def _search_financial_documents(
        query: str,
        ticker: str,
        curr_date: str,
    ) -> str:
        """按问题选择结构化基本面 API、文档 RAG 或两者。"""
        return search_financial_documents(
            query,
            ticker,
            curr_date,
            service=service,
        )

    return _search_financial_documents
