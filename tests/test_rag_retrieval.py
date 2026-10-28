"""R-08 Hybrid Retrieval 的最小冒烟测试。"""

from datetime import date

from tradingagents.rag.chunking import DocumentChunk
from tradingagents.rag.documents import DocumentChunkMetadata, FinancialDocumentMetadata
from tradingagents.rag.embeddings import EmbeddingModelConfig, EmbeddingProvider
from tradingagents.rag.retrieval import HybridRetriever, IndexedChunk

VECTOR_SIZE = 1536


class FixedEmbeddingProvider(EmbeddingProvider):
    """测试用固定向量 Provider，让排序结果不依赖真实模型。"""

    def __init__(self, vectors: dict[str, tuple[float, ...]]) -> None:
        super().__init__(EmbeddingModelConfig())
        self.vectors = vectors

    def embed(self, texts):
        return tuple(self.vectors[text] for text in texts)


def unit_vector(index: int) -> tuple[float, ...]:
    values = [0.0] * VECTOR_SIZE
    values[index] = 1.0
    return tuple(values)


def make_document(document_id: str, *, ticker: str = "AAPL", available_at: date = date(2025, 1, 1), document_type: str = "quarterly_report") -> FinancialDocumentMetadata:
    return FinancialDocumentMetadata(
        document_id=document_id,
        ticker=ticker,
        document_type=document_type,
        title=document_id,
        source_url=f"https://example.com/{document_id}.html",
        source_hash=(document_id.encode().hex() + "0" * 64)[:64],
        published_at=available_at,
        available_at=available_at,
        language="en",
    )


def make_indexed_chunk(document: FinancialDocumentMetadata, chunk_id: str, content: str, vector):
    return IndexedChunk(
        document=document,
        chunk=DocumentChunk(
            metadata=DocumentChunkMetadata(
                chunk_id=chunk_id,
                document_id=document.document_id,
                ordinal=0,
                section_title="Management Discussion",
                char_start=0,
                char_end=max(1, len(content)),
                token_count=max(1, len(content.split())),
            ),
            content=content,
        ),
        embedding=vector,
    )


def test_hybrid_search_filters_future_documents_and_returns_citation_fields():
    """主路径：未来文档和其他股票在候选阶段被排除。"""
    query_vector = unit_vector(0)
    provider = FixedEmbeddingProvider({"revenue": query_vector})
    old_doc = make_document("aapl-old")
    future_doc = make_document("aapl-future", available_at=date(2025, 2, 1))
    msft_doc = make_document("msft-old", ticker="MSFT")
    retriever = HybridRetriever(
        (
            make_indexed_chunk(old_doc, "old-1", "Revenue increased.", query_vector),
            make_indexed_chunk(future_doc, "future-1", "Revenue forecast.", query_vector),
            make_indexed_chunk(msft_doc, "msft-1", "Revenue increased.", query_vector),
        ),
        provider,
    )

    hits = retriever.search("revenue", ticker="AAPL", as_of=date(2025, 1, 31))

    assert [hit.chunk_id for hit in hits] == ["old-1"]
    assert hits[0].source_url == "https://example.com/aapl-old.html"
    assert hits[0].available_at == date(2025, 1, 1)


def test_rrf_merges_vector_only_and_keyword_only_candidates():
    """融合边界：向量命中和关键词命中不同片段时，两者都进入结果。"""
    query_vector = unit_vector(0)
    provider = FixedEmbeddingProvider({"revenue": query_vector})
    document = make_document("aapl-hybrid")
    vector_only = make_indexed_chunk(document, "vector-1", "Macro outlook.", query_vector)
    keyword_only = make_indexed_chunk(document, "keyword-1", "Revenue growth.", unit_vector(1))
    retriever = HybridRetriever((vector_only, keyword_only), provider)

    hits = retriever.search("revenue", ticker="AAPL", as_of=date(2025, 1, 31), top_k=2)

    assert {hit.chunk_id for hit in hits} == {"vector-1", "keyword-1"}
    assert next(hit for hit in hits if hit.chunk_id == "vector-1").vector_rank == 1
    assert next(hit for hit in hits if hit.chunk_id == "keyword-1").keyword_rank == 1


def test_weighted_rrf_can_prioritize_keyword_rank():
    document = make_document("weighted")
    vector_only = make_indexed_chunk(document, "vector-1", "semantic evidence.", unit_vector(1))
    keyword_only = make_indexed_chunk(document, "keyword-1", "revenue exact.", unit_vector(2))
    provider = FixedEmbeddingProvider({"revenue": unit_vector(1)})

    keyword_heavy = HybridRetriever(
        (vector_only, keyword_only),
        provider,
        candidate_k=2,
        keyword_weight=4.0,
        vector_weight=1.0,
    )

    assert keyword_heavy.search("revenue", ticker="AAPL", as_of=date(2025, 1, 1), top_k=2)[0].chunk_id == "keyword-1"


def test_document_type_filter_and_empty_query_guard():
    """边界：文档类型可过滤，空查询不能触发 Embedding 调用。"""
    query_vector = unit_vector(0)
    provider = FixedEmbeddingProvider({"risk": query_vector})
    annual = make_document("aapl-annual", document_type="annual_report")
    release = make_document("aapl-release", document_type="earnings_release")
    retriever = HybridRetriever(
        (
            make_indexed_chunk(annual, "annual-1", "Risk factors.", query_vector),
            make_indexed_chunk(release, "release-1", "Risk factors.", query_vector),
        ),
        provider,
    )

    hits = retriever.search(
        "risk",
        ticker="AAPL",
        as_of=date(2025, 1, 31),
        document_types={"annual_report"},
    )

    assert [hit.chunk_id for hit in hits] == ["annual-1"]
