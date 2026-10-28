"""R-13：把真实 PostgreSQL RAG 检索接入基本面 Agent。

这个模块只负责适配边界：调用 ``PostgresRetriever``、校验证据、整理 JSON
可序列化结果并记录一次检索 Trace。它不把数据库连接或 SQL 写进 Agent 节点，
因此基本面 Agent 仍然只依赖 ``FinancialSearchService`` 的函数契约。
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal

from sqlalchemy import Engine

from tradingagents.rag.embeddings import (
    EmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from tradingagents.rag.evidence import build_database_evidence_bundle
from tradingagents.rag.guards import filter_retrieval_hits
from tradingagents.rag.online_fallback import OnlineSecFallback
from tradingagents.rag.postgres import create_postgres_engine
from tradingagents.rag.postgres_retrieval import PostgresRetriever
from tradingagents.rag.retrieval import RetrievalHit

RagStrategy = Literal["keyword", "vector", "hybrid"]


def _fingerprint(query: str, ticker: str, as_of: date) -> str:
    """只记录不可逆指纹，避免 Trace 重复保存完整用户问题。"""
    raw = f"{ticker}|{as_of.isoformat()}|{query.strip()}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _hit_payload(hit: RetrievalHit) -> dict[str, Any]:
    """把命中转换为轻量元数据，正文统一放在 evidence.citations 中。

    ToolNode 会把整个 JSON 回写给下一次 LLM 调用。若 hits 和
    evidence.citations 同时携带正文，同一个 Chunk 会被重复放入上下文，
    增加网关处理时间；引用正文仍保留在 evidence 中，审计信息没有丢失。
    """
    return {
        "chunk_id": hit.chunk_id,
        "document_id": hit.document_id,
        "ticker": hit.ticker,
        "document_type": hit.document_type,
        "source_url": hit.source_url,
        "published_at": hit.published_at.isoformat(),
        "available_at": hit.available_at.isoformat(),
        "section": hit.section_title,
        "vector_score": hit.vector_score,
        "keyword_score": hit.keyword_score,
        "fused_score": hit.fused_score,
        "vector_rank": hit.vector_rank,
        "keyword_rank": hit.keyword_rank,
    }


@dataclass
class PostgresRagSearchAdapter:
    """给 ``FinancialSearchService`` 使用的真实数据库 RAG Callable。"""

    retriever: PostgresRetriever
    strategy: RagStrategy = "hybrid"
    top_k: int = 10
    online_fallback: OnlineSecFallback | None = None
    run_id_factory: Callable[[], str] = lambda: str(uuid.uuid4())

    def __post_init__(self) -> None:
        if self.strategy not in {"keyword", "vector", "hybrid"}:
            raise ValueError(f"unsupported RAG strategy: {self.strategy}")
        if not 1 <= self.top_k <= self.retriever.candidate_k:
            raise ValueError("top_k must be within the retriever candidate budget")

    def _retrieve(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
    ) -> tuple[RetrievalHit, ...]:
        """按固定策略取候选；日期和股票过滤由数据库检索器负责。"""
        search = getattr(self.retriever, f"{self.strategy}_search")
        return search(query, ticker=ticker, as_of=as_of, top_k=self.top_k)

    def __call__(self, query: str, ticker: str, as_of: date) -> dict[str, Any]:
        """执行一次 RAG 搜索并返回 Agent 可读的证据与 Trace。"""
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        run_id = self.run_id_factory()
        normalized_ticker = ticker.strip().upper()
        verbose = os.getenv("TRADINGAGENTS_RAG_VERBOSE", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if verbose:
            print(
                f"[RAG开始] ticker={normalized_ticker} | as_of={as_of} | "
                f"strategy={self.strategy} | top_k={self.top_k} | query={query.strip()[:120]}",
                flush=True,
            )
        hits = self._retrieve(query, ticker=normalized_ticker, as_of=as_of)
        guard = filter_retrieval_hits(
            hits,
            ticker=normalized_ticker,
            trade_date=as_of,
        )
        if any(hit.available_at > as_of for hit in hits):
            raise ValueError("citation is not available at the analysis date")
        hits = guard.hits
        source = "postgres"
        if not hits and self.online_fallback is not None:
            hits = self.online_fallback.search(
                query,
                ticker=normalized_ticker,
                as_of=as_of,
                top_k=self.top_k,
            )
            source = "online_sec"
            guard = filter_retrieval_hits(
                hits,
                ticker=normalized_ticker,
                trade_date=as_of,
            )
            hits = guard.hits
        evidence = (
            build_database_evidence_bundle(
                hits,
                query=query,
                ticker=normalized_ticker,
                as_of=as_of,
            )
            if hits
            else None
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        documents = tuple(dict.fromkeys(hit.document_id for hit in hits))
        if verbose:
            print(
                f"[RAG完成] hits={len(hits)} | documents={len(documents)} | "
                f"citations={len(evidence.citations) if evidence else 0} | "
                f"elapsed={elapsed_ms}ms | future_safe=True",
                flush=True,
            )
        return {
            "strategy": self.strategy,
            "source": source,
            "query": query.strip(),
            "ticker": normalized_ticker,
            "as_of": as_of.isoformat(),
            "hits": [_hit_payload(hit) for hit in hits],
            "evidence": evidence.model_dump(mode="json") if evidence else None,
            "guard": {
                "allowed": guard.allowed,
                "reason": guard.reason,
                "error_code": guard.error_code,
            },
            "trace": {
                "run_id": run_id,
                "query_fingerprint": _fingerprint(query, normalized_ticker, as_of),
                "started_at": started_at,
                "strategy": self.strategy,
                "candidate_k": self.retriever.candidate_k,
                "returned_hits": len(hits),
                "returned_documents": len(documents),
                "retrieval_calls": 2 if self.strategy == "hybrid" else 1,
                "embedding_calls": 1 if self.strategy in {"vector", "hybrid"} else 0,
                "elapsed_ms": elapsed_ms,
                "embedding_provider": self.retriever.embedding_provider.config.provider,
                "embedding_model": self.retriever.embedding_provider.config.model_name,
                "embedding_dimensions": self.retriever.embedding_provider.config.dimensions,
                "query_token_estimate": len(query.split()),
                "token_usage": None,
                "cost_usd": None,
                "cost_status": "not_available_from_provider",
                "error_code": None,
                "retryable": False,
            },
        }


def create_postgres_rag_search(
    *,
    engine: Engine | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    strategy: RagStrategy | None = None,
    top_k: int = 10,
) -> PostgresRagSearchAdapter:
    """按环境变量组装生产搜索函数，便于显式注入 TradingAgentsGraph。"""
    provider_name = os.getenv("TRADINGAGENTS_EMBEDDING_PROVIDER", "ollama").lower()
    if embedding_provider is None:
        if provider_name == "ollama":
            embedding_provider = OllamaEmbeddingProvider()
        elif provider_name in {"openai", "openai_compatible"}:
            embedding_provider = OpenAIEmbeddingProvider()
        else:
            raise ValueError(f"unsupported embedding provider: {provider_name}")
    retriever = PostgresRetriever(
        engine=engine or create_postgres_engine(),
        embedding_provider=embedding_provider,
    )
    configured_top_k = int(os.getenv("TRADINGAGENTS_RAG_TOP_K", str(top_k)))
    online_fallback = None
    if os.getenv("TRADINGAGENTS_ENABLE_ONLINE_FALLBACK", "false").lower() in {
        "1", "true", "yes", "on"
    }:
        online_fallback = OnlineSecFallback(embedding_provider)
    return PostgresRagSearchAdapter(
        retriever=retriever,
        strategy=strategy or os.getenv("TRADINGAGENTS_RAG_STRATEGY", "hybrid"),
        top_k=configured_top_k,
        online_fallback=online_fallback,
    )
