"""R-12-D：直接基于 PostgreSQL/pgvector 的真实检索适配器。

这个模块把已有的内存版 ``HybridRetriever`` 接到真实数据库。数据库层先
执行股票和 ``available_at`` 日期过滤，再分别执行 PostgreSQL 全文检索和
pgvector 余弦距离排序；Hybrid 使用 RRF 合并两路结果，返回统一的
``RetrievalHit``，因此上层 Agent 不需要区分数据来自哪一种索引。
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine, bindparam, text

from tradingagents.rag.embeddings import EmbeddingProvider
from tradingagents.rag.retrieval import RetrievalHit

DEFAULT_DATABASE_CANDIDATE_K = 20
DEFAULT_DATABASE_RRF_K = 60
_ASCII_TERM_RE = re.compile(r"[A-Za-z0-9_]+")
_KEYWORD_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "current",
    "date",
    "for",
    "from",
    "in",
    "latest",
    "of",
    "on",
    "the",
    "to",
    "what",
}


@dataclass(frozen=True)
class PostgresRetriever:
    """面向 ``documents`` 和 ``document_chunks`` 表的真实检索器。"""

    engine: Engine
    embedding_provider: EmbeddingProvider
    candidate_k: int = DEFAULT_DATABASE_CANDIDATE_K
    rrf_k: int = DEFAULT_DATABASE_RRF_K
    keyword_weight: float = 1.0
    vector_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.candidate_k < 1:
            raise ValueError("candidate_k must be positive")
        if self.rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if self.keyword_weight < 0 or self.vector_weight < 0:
            raise ValueError("RRF weights must be non-negative")
        if self.keyword_weight + self.vector_weight == 0:
            raise ValueError("RRF weights must not both be zero")

    @staticmethod
    def _validate_query(query: str, top_k: int, candidate_k: int) -> tuple[str, int]:
        """在访问数据库前拦截空查询和超出候选预算的请求。"""
        normalized = " ".join(query.split())
        if not normalized:
            raise ValueError("query must not be empty")
        if not 1 <= top_k <= candidate_k:
            raise ValueError(f"top_k must be between 1 and {candidate_k}")
        return normalized, top_k

    @staticmethod
    def _query_vector(vector: Sequence[float]) -> str:
        """把已校验的向量转成 pgvector 可解析的文本参数。"""
        return "[" + ",".join(str(float(value)) for value in vector) + "]"

    @staticmethod
    def _keyword_query(query: str) -> str:
        """把查询安全转换为 OR 前缀词，避免中英文 AND 导致全部无召回。"""
        terms = {
            term.lower()
            for term in _ASCII_TERM_RE.findall(query)
            if term.lower() not in _KEYWORD_STOPWORDS and len(term) > 1
        }
        # 词项只来自正则提取结果，不能携带 tsquery 操作符，避免查询注入。
        return " | ".join(f"{term}:*" for term in sorted(terms))

    @staticmethod
    def _to_hit(row: dict, *, vector_rank: int | None = None, keyword_rank: int | None = None,
                fused_score: float = 0.0) -> RetrievalHit:
        """把 SQL 行转换成上层统一的可引用检索结果。"""
        return RetrievalHit(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            ticker=row["ticker"],
            document_type=row["document_type"],
            source_url=row["source_url"],
            published_at=row["published_at"],
            available_at=row["available_at"],
            section_title=row["section_title"],
            content=row["content"],
            vector_score=float(row.get("vector_score", 0.0) or 0.0),
            keyword_score=float(row.get("keyword_score", 0.0) or 0.0),
            fused_score=fused_score,
            vector_rank=vector_rank,
            keyword_rank=keyword_rank,
        )

    @staticmethod
    def _document_type_clause(document_types: Collection[str] | None) -> tuple[str, dict[str, object]]:
        """生成参数化的文档类型条件，避免拼接用户输入到 SQL。"""
        allowed = tuple(sorted(set(document_types or ())))
        if not allowed:
            return "", {}
        return " AND d.document_type = ANY(:document_types)", {"document_types": list(allowed)}

    def hydrate_hits(self, chunk_ids: Collection[str]) -> dict[str, RetrievalHit]:
        """Read authoritative Chunk text and metadata after an external index hit."""
        ids = tuple(dict.fromkeys(str(item).strip() for item in chunk_ids if str(item).strip()))
        if not ids:
            return {}
        statement = text(
            """
            SELECT c.chunk_id, c.document_id, d.ticker, d.document_type,
                   d.source_url, d.published_at, d.available_at,
                   c.section_title, c.content
            FROM document_chunks AS c
            JOIN documents AS d ON d.document_id = c.document_id
            WHERE c.chunk_id IN :chunk_ids
            """
        ).bindparams(bindparam("chunk_ids", expanding=True))
        with self.engine.connect() as connection:
            rows = connection.execute(statement, {"chunk_ids": list(ids)}).mappings().all()
        return {row["chunk_id"]: self._to_hit(dict(row)) for row in rows}

    def keyword_search(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
        document_types: Collection[str] | None = None,
        top_k: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        """使用 ``content_tsv`` 做全文检索，并先执行金融日期边界过滤。"""
        normalized, top_k = self._validate_query(query, top_k, self.candidate_k)
        keyword_query = self._keyword_query(normalized)
        if not keyword_query:
            return ()
        type_clause, type_params = self._document_type_clause(document_types)
        statement = text(
            f"""
            SELECT c.chunk_id, c.document_id, d.ticker, d.document_type,
                   d.source_url, d.published_at, d.available_at,
                   c.section_title, c.content,
                   ts_rank_cd(c.content_tsv, to_tsquery('simple', :keyword_query))
                       AS keyword_score
            FROM document_chunks AS c
            JOIN documents AS d ON d.document_id = c.document_id
            WHERE d.ticker = :ticker
              AND d.available_at <= :as_of
              AND c.content_tsv @@ to_tsquery('simple', :keyword_query)
              {type_clause}
            ORDER BY keyword_score DESC, c.chunk_id
            LIMIT :limit
            """
        )
        params = {
            "keyword_query": keyword_query,
            "ticker": ticker.strip().upper(),
            "as_of": as_of,
            "limit": min(top_k, self.candidate_k),
            **type_params,
        }
        with self.engine.connect() as connection:
            rows = connection.execute(statement, params).mappings().all()
        return tuple(
            self._to_hit(dict(row), keyword_rank=rank)
            for rank, row in enumerate(rows, start=1)
        )

    def vector_search(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
        document_types: Collection[str] | None = None,
        top_k: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        """调用真实 Embedding Provider，再用 pgvector 余弦距离排序。"""
        normalized, top_k = self._validate_query(query, top_k, self.candidate_k)
        vectors = self.embedding_provider.embed([normalized])
        if len(vectors) != 1:
            raise ValueError("embedding provider returned an unexpected query batch size")
        vector_text = self._query_vector(vectors[0])
        type_clause, type_params = self._document_type_clause(document_types)
        statement = text(
            f"""
            SELECT c.chunk_id, c.document_id, d.ticker, d.document_type,
                   d.source_url, d.published_at, d.available_at,
                   c.section_title, c.content,
                   1 - (c.embedding <=> CAST(:query_vector AS vector))
                       AS vector_score
            FROM document_chunks AS c
            JOIN documents AS d ON d.document_id = c.document_id
            WHERE d.ticker = :ticker
              AND d.available_at <= :as_of
              AND c.embedding IS NOT NULL
              {type_clause}
            ORDER BY c.embedding <=> CAST(:query_vector AS vector), c.chunk_id
            LIMIT :limit
            """
        )
        params = {
            "query_vector": vector_text,
            "ticker": ticker.strip().upper(),
            "as_of": as_of,
            "limit": min(top_k, self.candidate_k),
            **type_params,
        }
        with self.engine.connect() as connection:
            rows = connection.execute(statement, params).mappings().all()
        return tuple(
            self._to_hit(dict(row), vector_rank=rank)
            for rank, row in enumerate(rows, start=1)
        )

    def hybrid_search(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
        document_types: Collection[str] | None = None,
        top_k: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        """将关键词和向量两路候选按 Reciprocal Rank Fusion 合并。"""
        keyword_hits = self.keyword_search(
            query, ticker=ticker, as_of=as_of, document_types=document_types,
            top_k=self.candidate_k,
        )
        vector_hits = self.vector_search(
            query, ticker=ticker, as_of=as_of, document_types=document_types,
            top_k=self.candidate_k,
        )
        keyword_by_id = {hit.chunk_id: hit for hit in keyword_hits}
        vector_by_id = {hit.chunk_id: hit for hit in vector_hits}
        all_ids = set(keyword_by_id) | set(vector_by_id)
        fused: list[RetrievalHit] = []
        for chunk_id in all_ids:
            keyword_hit = keyword_by_id.get(chunk_id)
            vector_hit = vector_by_id.get(chunk_id)
            keyword_rank = keyword_hits.index(keyword_hit) + 1 if keyword_hit else None
            vector_rank = vector_hits.index(vector_hit) + 1 if vector_hit else None
            score = 0.0
            if keyword_rank is not None:
                score += self.keyword_weight / (self.rrf_k + keyword_rank)
            if vector_rank is not None:
                score += self.vector_weight / (self.rrf_k + vector_rank)
            source = vector_hit or keyword_hit
            assert source is not None
            fused.append(
                RetrievalHit(
                    chunk_id=source.chunk_id,
                    document_id=source.document_id,
                    ticker=source.ticker,
                    document_type=source.document_type,
                    source_url=source.source_url,
                    published_at=source.published_at,
                    available_at=source.available_at,
                    section_title=source.section_title,
                    content=source.content,
                    vector_score=vector_hit.vector_score if vector_hit else 0.0,
                    keyword_score=keyword_hit.keyword_score if keyword_hit else 0.0,
                    fused_score=score,
                    vector_rank=vector_rank,
                    keyword_rank=keyword_rank,
                )
            )
        fused.sort(key=lambda hit: (-hit.fused_score, hit.chunk_id))
        return tuple(fused[:top_k])
