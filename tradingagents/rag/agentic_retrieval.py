"""R-11：受约束的 Agentic Retrieval 运行器。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tradingagents.rag.chunking import estimate_token_count
from tradingagents.rag.retrieval import RetrievalHit

StopReason = Literal[
    "EVIDENCE_FOUND",
    "EVIDENCE_INSUFFICIENT",
    "DUPLICATE_QUERY",
    "MAX_ROUNDS",
    "MAX_QUERIES",
    "CONTEXT_BUDGET",
    "RETRIEVAL_ERROR",
    "INVALID_QUERY",
]
RetrievalFn = Callable[[str], Sequence[RetrievalHit]]
QueryRewriteFn = Callable[[str, int], str | None]


class AgenticRetrievalConfig(BaseModel):
    """Agentic Retrieval 的确定性预算。"""

    model_config = ConfigDict(extra="forbid")

    max_rounds: int = Field(default=2, ge=1, le=8)
    max_queries: int = Field(default=3, ge=1, le=16)
    max_chunks_per_round: int = Field(default=6, ge=1, le=20)
    max_query_chars: int = Field(default=512, ge=1, le=4096)
    max_context_chars: int = Field(default=12000, ge=100, le=100000)
    max_context_tokens: int = Field(default=3000, ge=1, le=20000)

    @model_validator(mode="after")
    def validate_budget(self) -> AgenticRetrievalConfig:
        """配置必须允许至少执行一轮检索。"""
        if self.max_rounds < 1 or self.max_queries < 1:
            raise ValueError("max_rounds and max_queries must be positive")
        return self


class RetrievalTrace(BaseModel):
    """每一轮检索的可观测记录。"""

    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=1)
    query: str = Field(min_length=1)
    query_fingerprint: str = Field(min_length=8, max_length=64)
    hits_returned: int = Field(ge=0)
    unique_hits_added: int = Field(ge=0)
    stop_reason: str


class AgenticRetrievalResult(BaseModel):
    """受预算约束的检索结果、上下文和停止原因。"""

    model_config = ConfigDict(extra="forbid")

    success: bool
    hits: tuple[RetrievalHit, ...] = ()
    context: str = ""
    traces: tuple[RetrievalTrace, ...] = ()
    queries_used: int = Field(default=0, ge=0)
    rounds_used: int = Field(default=0, ge=0)
    stop_reason: StopReason
    error_code: str | None = None
    retryable: bool = False


def query_fingerprint(query: str) -> str:
    """用大小写和空白归一化后的 Query 生成稳定指纹。"""
    normalized = " ".join(query.split()).lower()
    return sha256(normalized.encode()).hexdigest()[:16]


class ConstrainedRetrievalRunner:
    """给检索工具增加轮数、查询次数、去重和上下文预算。"""

    def __init__(
        self,
        retrieval_fn: RetrievalFn,
        *,
        query_rewriter: QueryRewriteFn | None = None,
        config: AgenticRetrievalConfig | None = None,
    ) -> None:
        self._retrieval_fn = retrieval_fn
        self._query_rewriter = query_rewriter
        self._config = config or AgenticRetrievalConfig()

    def _result(
        self,
        *,
        success: bool,
        hits: Sequence[RetrievalHit],
        context: str,
        traces: Sequence[RetrievalTrace],
        queries_used: int,
        stop_reason: StopReason,
        error_code: str | None = None,
        retryable: bool = False,
    ) -> AgenticRetrievalResult:
        return AgenticRetrievalResult(
            success=success,
            hits=tuple(hits),
            context=context,
            traces=tuple(traces),
            queries_used=queries_used,
            rounds_used=len(traces),
            stop_reason=stop_reason,
            error_code=error_code,
            retryable=retryable,
        )

    def _append_hits(
        self,
        context: str,
        hits: Sequence[RetrievalHit],
        seen_chunk_ids: set[str],
    ) -> tuple[str, list[RetrievalHit], bool]:
        """按片段去重并写入上下文；超预算时立即停止追加。"""
        accepted: list[RetrievalHit] = []
        current = context
        for hit in hits:
            if hit.chunk_id in seen_chunk_ids:
                continue
            block = f"[{hit.chunk_id}] {hit.section_title}\n{hit.content.strip()}"
            candidate = f"{current}\n\n{block}".strip()
            if len(candidate) > self._config.max_context_chars:
                return current, accepted, True
            if estimate_token_count(candidate) > self._config.max_context_tokens:
                return current, accepted, True
            seen_chunk_ids.add(hit.chunk_id)
            accepted.append(hit)
            current = candidate
        return current, accepted, False

    def run(self, initial_query: str) -> AgenticRetrievalResult:
        """执行有限轮检索，证据不足时按规则改写或停止。"""
        current_query = " ".join(initial_query.split())
        if not current_query or len(current_query) > self._config.max_query_chars:
            return self._result(
                success=False,
                hits=(),
                context="",
                traces=(),
                queries_used=0,
                stop_reason="INVALID_QUERY",
                error_code="INVALID_QUERY",
            )

        used_fingerprints: set[str] = set()
        seen_chunk_ids: set[str] = set()
        all_hits: list[RetrievalHit] = []
        traces: list[RetrievalTrace] = []
        context = ""
        queries_used = 0

        for round_index in range(1, self._config.max_rounds + 1):
            if queries_used >= self._config.max_queries:
                return self._result(
                    success=bool(all_hits),
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="MAX_QUERIES",
                )

            fingerprint = query_fingerprint(current_query)
            if fingerprint in used_fingerprints:
                return self._result(
                    success=bool(all_hits),
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="DUPLICATE_QUERY",
                )
            used_fingerprints.add(fingerprint)
            queries_used += 1

            try:
                raw_hits = self._retrieval_fn(current_query)
            except Exception as exc:  # noqa: BLE001 - 统一记录检索失败并停止
                traces.append(
                    RetrievalTrace(
                        round_index=round_index,
                        query=current_query,
                        query_fingerprint=fingerprint,
                        hits_returned=0,
                        unique_hits_added=0,
                        stop_reason="RETRIEVAL_ERROR",
                    )
                )
                return self._result(
                    success=bool(all_hits),
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="RETRIEVAL_ERROR",
                    error_code=f"RETRIEVAL_ERROR: {type(exc).__name__}: {exc}",
                    retryable=True,
                )

            limited_hits = tuple(raw_hits[: self._config.max_chunks_per_round])
            context, new_hits, budget_exceeded = self._append_hits(
                context,
                limited_hits,
                seen_chunk_ids,
            )
            all_hits.extend(new_hits)
            traces.append(
                RetrievalTrace(
                    round_index=round_index,
                    query=current_query,
                    query_fingerprint=fingerprint,
                    hits_returned=len(limited_hits),
                    unique_hits_added=len(new_hits),
                    stop_reason=("CONTEXT_BUDGET" if budget_exceeded else "EVIDENCE_FOUND"),
                )
            )

            if budget_exceeded:
                return self._result(
                    success=bool(all_hits),
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="CONTEXT_BUDGET",
                    error_code="CONTEXT_BUDGET",
                )
            if new_hits:
                return self._result(
                    success=True,
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="EVIDENCE_FOUND",
                )

            if round_index >= self._config.max_rounds:
                return self._result(
                    success=False,
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="MAX_ROUNDS",
                )
            if queries_used >= self._config.max_queries:
                return self._result(
                    success=False,
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="MAX_QUERIES",
                )
            if self._query_rewriter is None:
                return self._result(
                    success=False,
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="EVIDENCE_INSUFFICIENT",
                )

            rewritten = self._query_rewriter(current_query, round_index)
            if not rewritten or len(rewritten.strip()) > self._config.max_query_chars:
                return self._result(
                    success=False,
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="EVIDENCE_INSUFFICIENT",
                )
            next_query = " ".join(rewritten.split())
            if query_fingerprint(next_query) in used_fingerprints:
                return self._result(
                    success=False,
                    hits=all_hits,
                    context=context,
                    traces=traces,
                    queries_used=queries_used,
                    stop_reason="DUPLICATE_QUERY",
                )
            current_query = next_query

        return self._result(
            success=bool(all_hits),
            hits=all_hits,
            context=context,
            traces=traces,
            queries_used=queries_used,
            stop_reason="MAX_ROUNDS",
        )
