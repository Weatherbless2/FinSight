from datetime import date

from tradingagents.rag.guards import filter_retrieval_hits
from tradingagents.rag.retrieval import RetrievalHit


def make_hit(ticker="NVDA", document_id="doc", available_at=date(2025, 1, 1)):
    return RetrievalHit(
        chunk_id=document_id,
        document_id=document_id,
        ticker=ticker,
        document_type="annual_report",
        source_url="https://example.com/doc",
        published_at=available_at,
        available_at=available_at,
        section_title="Business",
        content="Revenue increased.",
        vector_score=1,
        keyword_score=1,
        fused_score=1,
        vector_rank=1,
        keyword_rank=1,
    )


def test_guard_filters_future_cross_ticker_and_acl_documents():
    decision = filter_retrieval_hits(
        (make_hit(), make_hit(document_id="future", available_at=date(2025, 4, 1)), make_hit("MSFT", "msft")),
        ticker="NVDA",
        trade_date=date(2025, 3, 1),
        allowed_document_ids={"doc"},
    )

    assert decision.allowed is True
    assert [hit.document_id for hit in decision.hits] == ["doc"]


def test_guard_returns_structured_refusal_when_evidence_is_insufficient():
    decision = filter_retrieval_hits((), ticker="NVDA", trade_date=date(2025, 3, 1))

    assert decision.allowed is False
    assert decision.reason == "evidence_insufficient"
    assert decision.error_code == "EVIDENCE_INSUFFICIENT"
