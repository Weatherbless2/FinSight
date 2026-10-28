"""R-08 OpenSearch candidate retrieval with PostgreSQL evidence hydration."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import date

from tradingagents.rag.embeddings import EmbeddingProvider
from tradingagents.rag.opensearch import OpenSearchClient, build_bm25_query, build_knn_query
from tradingagents.rag.postgres_retrieval import PostgresRetriever
from tradingagents.rag.retrieval import RetrievalHit

HydrateHits = Callable[[Collection[str]], dict[str, RetrievalHit]]


def create_opensearch_retriever(
    *,
    client: OpenSearchClient,
    postgres_retriever: PostgresRetriever,
    index: str = "rag-chunks-v1",
    candidate_k: int = 20,
    rrf_k: int = 60,
    keyword_weight: float = 1.0,
    vector_weight: float = 1.0,
) -> OpenSearchRetriever:
    """Build the external-index path while keeping PostgreSQL as evidence source."""
    return OpenSearchRetriever(
        client=client,
        embedding_provider=postgres_retriever.embedding_provider,
        hydrate_hits=postgres_retriever.hydrate_hits,
        index=index,
        candidate_k=candidate_k,
        rrf_k=rrf_k,
        keyword_weight=keyword_weight,
        vector_weight=vector_weight,
    )


@dataclass(frozen=True)
class OpenSearchRetriever:
    """Use OpenSearch for candidates, then hydrate trusted Chunk data by ID."""

    client: OpenSearchClient
    embedding_provider: EmbeddingProvider
    hydrate_hits: HydrateHits
    index: str = "rag-chunks-v1"
    candidate_k: int = 20
    rrf_k: int = 60
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
    def _ids(response: dict) -> tuple[tuple[str, float], ...]:
        hits = response.get("hits", {}).get("hits", [])
        return tuple(
            (str(item.get("_source", {}).get("chunk_id", item.get("_id", ""))), float(item.get("_score") or 0.0))
            for item in hits
            if item.get("_source", {}).get("chunk_id", item.get("_id"))
        )

    def _hydrate(
        self,
        ranked: list[tuple[str, float, float, int | None, int | None]],
        *,
        ticker: str,
        as_of: date,
        top_k: int,
    ) -> tuple[RetrievalHit, ...]:
        by_id = self.hydrate_hits([chunk_id for chunk_id, *_ in ranked])
        results: list[RetrievalHit] = []
        for chunk_id, keyword_score, vector_score, keyword_rank, vector_rank in ranked:
            hit = by_id.get(chunk_id)
            if hit is None or hit.ticker != ticker.strip().upper() or hit.available_at > as_of:
                continue
            results.append(
                RetrievalHit(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    ticker=hit.ticker,
                    document_type=hit.document_type,
                    source_url=hit.source_url,
                    published_at=hit.published_at,
                    available_at=hit.available_at,
                    section_title=hit.section_title,
                    content=hit.content,
                    vector_score=vector_score,
                    keyword_score=keyword_score,
                    fused_score=(
                        (self.keyword_weight / (self.rrf_k + keyword_rank) if keyword_rank else 0.0)
                        + (self.vector_weight / (self.rrf_k + vector_rank) if vector_rank else 0.0)
                    ),
                    vector_rank=vector_rank,
                    keyword_rank=keyword_rank,
                )
            )
        results.sort(key=lambda item: (-item.fused_score, item.chunk_id))
        return tuple(results[:top_k])

    def keyword_search(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
        tenant_id: str = "default",
        acl_tags: Collection[str] = (),
        document_types: Collection[str] = (),
        top_k: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        response = self.client.search(
            self.index,
            build_bm25_query(
                query,
                ticker=ticker,
                trade_date=as_of,
                tenant_id=tenant_id,
                acl_tags=acl_tags,
                document_types=document_types,
                top_k=self.candidate_k,
            ),
        )
        keyword = self._ids(response)
        ranked = [(chunk_id, score, 0.0, rank, None) for rank, (chunk_id, score) in enumerate(keyword, start=1)]
        return self._hydrate(ranked, ticker=ticker, as_of=as_of, top_k=top_k)

    def vector_search(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
        tenant_id: str = "default",
        acl_tags: Collection[str] = (),
        document_types: Collection[str] = (),
        top_k: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        vectors = self.embedding_provider.embed([query.strip()])
        if len(vectors) != 1:
            raise ValueError("embedding provider returned an unexpected query batch size")
        response = self.client.search(
            self.index,
            build_knn_query(
                vectors[0],
                ticker=ticker,
                trade_date=as_of,
                tenant_id=tenant_id,
                acl_tags=acl_tags,
                document_types=document_types,
                top_k=self.candidate_k,
            ),
        )
        vector = self._ids(response)
        ranked = [(chunk_id, 0.0, score, None, rank) for rank, (chunk_id, score) in enumerate(vector, start=1)]
        return self._hydrate(ranked, ticker=ticker, as_of=as_of, top_k=top_k)

    def hybrid_search(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
        tenant_id: str = "default",
        acl_tags: Collection[str] = (),
        document_types: Collection[str] = (),
        top_k: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        keyword_response = self.client.search(
            self.index,
            build_bm25_query(query, ticker=ticker, trade_date=as_of, tenant_id=tenant_id, acl_tags=acl_tags, document_types=document_types, top_k=self.candidate_k),
        )
        vectors = self.embedding_provider.embed([query.strip()])
        if len(vectors) != 1:
            raise ValueError("embedding provider returned an unexpected query batch size")
        vector_response = self.client.search(
            self.index,
            build_knn_query(vectors[0], ticker=ticker, trade_date=as_of, tenant_id=tenant_id, acl_tags=acl_tags, document_types=document_types, top_k=self.candidate_k),
        )
        keyword = self._ids(keyword_response)
        vector = self._ids(vector_response)
        keyword_ranks = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(keyword, start=1)}
        vector_ranks = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(vector, start=1)}
        ids = sorted(set(keyword_ranks) | set(vector_ranks))
        ranked = [
            (
                chunk_id,
                keyword_ranks.get(chunk_id, (None, 0.0))[1],
                vector_ranks.get(chunk_id, (None, 0.0))[1],
                keyword_ranks.get(chunk_id, (None, 0.0))[0],
                vector_ranks.get(chunk_id, (None, 0.0))[0],
            )
            for chunk_id in ids
        ]
        return self._hydrate(ranked, ticker=ticker, as_of=as_of, top_k=top_k)
