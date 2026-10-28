"""R-08：带金融日期过滤的向量 + 关键词 Hybrid Retrieval。"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date

from tradingagents.rag.chunking import DocumentChunk
from tradingagents.rag.documents import FinancialDocumentMetadata
from tradingagents.rag.embeddings import (
    POSTGRES_VECTOR_DIMENSIONS,
    EmbeddingProvider,
    validate_embedding_vector,
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")
DEFAULT_CANDIDATE_K = 20
DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class IndexedChunk:
    """文档元数据、Chunk 正文和已生成向量的组合。"""

    document: FinancialDocumentMetadata
    chunk: DocumentChunk
    embedding: tuple[float, ...]

    def __post_init__(self) -> None:
        """在进入检索器前校验父文档关系和向量维度。"""
        if self.document.document_id != self.chunk.metadata.document_id:
            raise ValueError("chunk document_id does not match parent document")
        vector = validate_embedding_vector(
            self.embedding,
            dimensions=POSTGRES_VECTOR_DIMENSIONS,
        )
        object.__setattr__(self, "embedding", vector)


@dataclass(frozen=True)
class RetrievalHit:
    """返回给上层 Agent 的可引用检索结果。"""

    chunk_id: str
    document_id: str
    ticker: str
    document_type: str
    source_url: str
    published_at: date
    available_at: date
    section_title: str
    content: str
    vector_score: float
    keyword_score: float
    fused_score: float
    vector_rank: int | None
    keyword_rank: int | None
    rerank_score: float = 0.0


def _tokens(text: str) -> tuple[str, ...]:
    """统一中英文和数字的轻量分词，后续可替换为 PostgreSQL tsvector。"""
    return tuple(token.lower() for token in _TOKEN_RE.findall(text))


def _keyword_score(query: str, content: str) -> float:
    """用词项覆盖率做可解释的关键词基线分数。"""
    query_counts = Counter(_tokens(query))
    if not query_counts:
        return 0.0
    content_counts = Counter(_tokens(content))
    matched = sum(min(count, content_counts[token]) for token, count in query_counts.items())
    return matched / sum(query_counts.values())


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class HybridRetriever:
    """先做确定性金融过滤，再融合向量和关键词候选。"""

    def __init__(
        self,
        chunks: Sequence[IndexedChunk],
        embedding_provider: EmbeddingProvider,
        *,
        candidate_k: int = DEFAULT_CANDIDATE_K,
        rrf_k: int = DEFAULT_RRF_K,
        keyword_weight: float = 1.0,
        vector_weight: float = 1.0,
    ) -> None:
        if candidate_k < 1:
            raise ValueError("candidate_k must be positive")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if keyword_weight < 0 or vector_weight < 0 or keyword_weight + vector_weight == 0:
            raise ValueError("RRF weights must be non-negative and not both zero")
        ids = [item.chunk.metadata.chunk_id for item in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("chunk_id must be unique in a retrieval index")
        self._chunks = tuple(chunks)
        self._embedding_provider = embedding_provider
        self._candidate_k = candidate_k
        self._rrf_k = rrf_k
        self._keyword_weight = keyword_weight
        self._vector_weight = vector_weight

    def search(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
        document_types: Collection[str] | None = None,
        top_k: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        """返回经过股票、日期和类型过滤后的 RRF 结果。"""
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if not 1 <= top_k <= self._candidate_k:
            raise ValueError(f"top_k must be between 1 and {self._candidate_k}")

        normalized_ticker = ticker.strip().upper()
        allowed_types = set(document_types or ())
        candidates = tuple(
            item
            for item in self._chunks
            if item.document.ticker == normalized_ticker
            and item.document.is_available_at(as_of)
            and (not allowed_types or item.document.document_type in allowed_types)
        )
        if not candidates:
            return ()

        query_vectors = self._embedding_provider.embed([normalized_query])
        if len(query_vectors) != 1:
            raise ValueError("embedding provider returned an unexpected query batch size")
        query_vector = validate_embedding_vector(
            query_vectors[0],
            dimensions=POSTGRES_VECTOR_DIMENSIONS,
        )

        vector_scored = sorted(
            [
                (_cosine_similarity(query_vector, item.embedding), item)
                for item in candidates
            ],
            key=lambda pair: (-pair[0], pair[1].chunk.metadata.chunk_id),
        )[: self._candidate_k]

        keyword_scored = []
        for item in candidates:
            score = _keyword_score(normalized_query, item.chunk.content)
            if score > 0.0:
                keyword_scored.append((score, item))
        keyword_scored.sort(key=lambda pair: (-pair[0], pair[1].chunk.metadata.chunk_id))
        keyword_scored = keyword_scored[: self._candidate_k]

        vector_rank = {
            item.chunk.metadata.chunk_id: (rank, score)
            for rank, (score, item) in enumerate(vector_scored, start=1)
        }
        keyword_rank = {
            item.chunk.metadata.chunk_id: (rank, score)
            for rank, (score, item) in enumerate(keyword_scored, start=1)
        }
        by_id = {
            item.chunk.metadata.chunk_id: item
            for _, item in vector_scored + keyword_scored
        }

        hits = []
        for chunk_id, item in by_id.items():
            vector_info = vector_rank.get(chunk_id)
            keyword_info = keyword_rank.get(chunk_id)
            fused_score = 0.0
            if vector_info is not None:
                fused_score += self._vector_weight / (self._rrf_k + vector_info[0])
            if keyword_info is not None:
                fused_score += self._keyword_weight / (self._rrf_k + keyword_info[0])
            hits.append(
                RetrievalHit(
                    chunk_id=chunk_id,
                    document_id=item.document.document_id,
                    ticker=item.document.ticker,
                    document_type=item.document.document_type,
                    source_url=item.document.source_url,
                    published_at=item.document.published_at,
                    available_at=item.document.available_at,
                    section_title=item.chunk.metadata.section_title,
                    content=item.chunk.content,
                    vector_score=vector_info[1] if vector_info else 0.0,
                    keyword_score=keyword_info[1] if keyword_info else 0.0,
                    fused_score=fused_score,
                    vector_rank=vector_info[0] if vector_info else None,
                    keyword_rank=keyword_info[0] if keyword_info else None,
                )
            )
        hits.sort(key=lambda hit: (-hit.fused_score, hit.chunk_id))
        return tuple(hits[:top_k])
