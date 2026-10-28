from datetime import date

from tradingagents.rag.rerank import rerank_hits
from tradingagents.rag.retrieval import RetrievalHit


def hit(chunk_id: str, document_id: str, content: str, fused: float) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        document_id=document_id,
        ticker="NVDA",
        document_type="annual_report",
        source_url="https://example.com/report",
        published_at=date(2025, 1, 1),
        available_at=date(2025, 1, 1),
        section_title="Business",
        content=content,
        vector_score=0.0,
        keyword_score=0.0,
        fused_score=fused,
        vector_rank=None,
        keyword_rank=None,
    )


def test_rerank_sorts_scores_and_removes_duplicate_content():
    candidates = (
        hit("a", "doc-1", "Revenue grew.", 0.2),
        hit("b", "doc-1", "Revenue grew.", 0.1),
        hit("c", "doc-2", "Margin improved.", 0.05),
    )
    result = rerank_hits("why", candidates, lambda _q, texts: [0.4, 0.9, 0.8], top_k=2)

    assert result.used_fallback is False
    assert [item.chunk_id for item in result.hits] == ["b", "c"]
    assert result.hits[0].rerank_score == 0.9


def test_rerank_failure_returns_deduplicated_rrf_fallback():
    candidates = (
        hit("a", "doc-1", "Revenue grew.", 0.2),
        hit("b", "doc-1", "Revenue grew.", 0.1),
        hit("c", "doc-2", "Margin improved.", 0.05),
    )
    result = rerank_hits("why", candidates, lambda _q, _texts: (_ for _ in ()).throw(TimeoutError("tei")), top_k=2)

    assert result.used_fallback is True
    assert [item.chunk_id for item in result.hits] == ["a", "c"]
    assert "TimeoutError" in (result.error or "")
