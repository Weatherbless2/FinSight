from datetime import date
from types import SimpleNamespace

from tradingagents.rag.opensearch_retrieval import OpenSearchRetriever
from tradingagents.rag.retrieval import RetrievalHit


def _hit(chunk_id, *, ticker="AAPL"):
    return RetrievalHit(
        chunk_id=chunk_id,
        document_id="doc-1",
        ticker=ticker,
        document_type="annual_report",
        source_url="https://example.com/doc",
        published_at=date(2025, 1, 1),
        available_at=date(2025, 1, 1),
        section_title="Risk",
        content="Revenue risk",
        vector_score=0,
        keyword_score=0,
        fused_score=0,
        vector_rank=None,
        keyword_rank=None,
    )


class FakeClient:
    def search(self, index, query):
        if "bool" in query["query"]:
            return {"hits": {"hits": [{"_id": "k1", "_score": 4.0, "_source": {"chunk_id": "k1"}}]}}
        return {"hits": {"hits": [{"_id": "v1", "_score": 0.9, "_source": {"chunk_id": "v1"}}]}}


class FakeProvider:
    config = SimpleNamespace(provider="test", model_name="bge-m3", dimensions=1024)

    def embed(self, texts):
        return [[0.1] * 1024]


def test_opensearch_retriever_hydrates_authoritative_hits_and_applies_filters():
    retriever = OpenSearchRetriever(
        client=FakeClient(),
        embedding_provider=FakeProvider(),
        hydrate_hits=lambda ids: {item: _hit(item) for item in ids},
    )
    hits = retriever.hybrid_search("revenue", ticker="aapl", as_of=date(2025, 2, 1), top_k=2)

    assert [hit.chunk_id for hit in hits] == ["k1", "v1"]
    assert hits[0].keyword_rank == 1
    assert hits[1].vector_rank == 1
