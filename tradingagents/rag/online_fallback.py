"""SEC 在线兜底检索：只在本地知识库没有命中时使用。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import cast

from tradingagents.rag.chunking import DocumentChunk, chunk_document
from tradingagents.rag.documents import DocumentType, FinancialDocumentMetadata
from tradingagents.rag.embeddings import EmbeddingProvider
from tradingagents.rag.ingestion import build_document_metadata, fetch_document
from tradingagents.rag.parsing import parse_html_document
from tradingagents.rag.retrieval import HybridRetriever, IndexedChunk, RetrievalHit
from tradingagents.rag.sec_filings import SECClient, SECFilingCandidate


class OnlineFallbackError(RuntimeError):
    """在线兜底无法取得可检索材料。"""


class OnlineSecFallback:
    """发现、下载并在内存中检索少量 SEC 文档，不直接修改数据库。"""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        *,
        user_agent: str | None = None,
        limit_per_form: int = 1,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.client = SECClient(user_agent=user_agent)
        self.limit_per_form = limit_per_form

    def _load_chunks(
        self,
        candidates: Sequence[SECFilingCandidate],
    ) -> tuple[dict[str, FinancialDocumentMetadata], tuple[DocumentChunk, ...]]:
        documents: dict[str, FinancialDocumentMetadata] = {}
        chunks: list[DocumentChunk] = []
        for candidate in candidates:
            fetched = fetch_document(candidate.source_url, user_agent=self.client.user_agent)
            metadata = build_document_metadata(
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
            parsed = parse_html_document(fetched, document_id=metadata.document_id)
            documents[metadata.document_id] = metadata
            chunks.extend(chunk_document(parsed))
        if not documents or not chunks:
            raise OnlineFallbackError("SEC 没有返回可检索的 HTML 财报")
        return documents, tuple(chunks)

    def search(
        self,
        query: str,
        *,
        ticker: str,
        as_of: date,
        top_k: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        """仅在内存中完成本次检索；调用方负责决定是否异步入库。"""
        candidates = self.client.discover_filings(
            ticker,
            as_of=as_of,
            forms=("10-K", "10-Q", "8-K"),
            limit_per_form=self.limit_per_form,
        )
        documents, chunks = self._load_chunks(candidates)
        vectors = self.embedding_provider.embed_chunks(chunks, batch_size=16)
        vector_by_id = {
            result.chunk_id: result.vector
            for result in vectors
            if result.status == "succeeded" and result.vector is not None
        }
        if not vector_by_id:
            raise OnlineFallbackError("在线财报 Embedding 失败，无法执行向量检索")
        indexed: list[IndexedChunk] = []
        for chunk in chunks:
            document = documents.get(chunk.metadata.document_id)
            if document is None or chunk.metadata.chunk_id not in vector_by_id:
                continue
            indexed.append(IndexedChunk(document, chunk, vector_by_id[chunk.metadata.chunk_id]))
        if not indexed:
            raise OnlineFallbackError("在线财报没有生成可用 Chunk")
        retriever = HybridRetriever(indexed, self.embedding_provider)
        return retriever.search(query, ticker=ticker, as_of=as_of, top_k=top_k)
