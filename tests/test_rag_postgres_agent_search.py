"""R-13 PostgreSQL RAG 到基本面 Agent 边界的确定性测试。"""

import json
from datetime import date
from types import SimpleNamespace

import pytest

from tradingagents.rag.agent_search import FinancialSearchService
from tradingagents.rag.postgres_agent_search import PostgresRagSearchAdapter
from tradingagents.rag.retrieval import RetrievalHit


def make_hit(*, ticker: str = "AAPL", available_at: date = date(2025, 1, 1)):
    return RetrievalHit(
        chunk_id="chunk-1",
        document_id="doc-1",
        ticker=ticker,
        document_type="annual_report",
        source_url="https://example.com/doc-1.html",
        published_at=date(2025, 1, 1),
        available_at=available_at,
        section_title="Risk Factors",
        content="The company faces supply chain risks.",
        vector_score=0.9,
        keyword_score=0.8,
        fused_score=0.03,
        vector_rank=1,
        keyword_rank=1,
    )


class FakeRetriever:
    candidate_k = 20
    embedding_provider = SimpleNamespace(
        config=SimpleNamespace(
            provider="ollama",
            model_name="nomic-embed-text",
            dimensions=1536,
        )
    )

    def __init__(self):
        self.calls = []

    def hybrid_search(self, query, *, ticker, as_of, top_k):
        self.calls.append(("hybrid", query, ticker, as_of, top_k))
        return (make_hit(ticker=ticker),)


def test_postgres_adapter_returns_json_serializable_evidence_and_trace():
    retriever = FakeRetriever()
    adapter = PostgresRagSearchAdapter(
        retriever=retriever,
        strategy="hybrid",
        run_id_factory=lambda: "run-test-1",
    )

    payload = adapter("What are the risks?", "aapl", date(2025, 1, 31))

    json.dumps(payload)
    assert payload["evidence"]["citations"][0]["chunk_id"] == "chunk-1"
    assert payload["trace"]["run_id"] == "run-test-1"
    assert payload["trace"]["returned_hits"] == 1
    assert payload["trace"]["retrieval_calls"] == 2
    assert payload["trace"]["cost_usd"] is None
    assert retriever.calls == [
        ("hybrid", "What are the risks?", "AAPL", date(2025, 1, 31), 10)
    ]


def test_postgres_adapter_verbose_trace(capsys, monkeypatch):
    """开启观测开关后，终端能直接看出 RAG 是否被调用。"""
    monkeypatch.setenv("TRADINGAGENTS_RAG_VERBOSE", "true")
    adapter = PostgresRagSearchAdapter(
        retriever=FakeRetriever(),
        run_id_factory=lambda: "run-verbose",
    )

    adapter("What are the risks?", "AAPL", date(2025, 1, 31))
    output = capsys.readouterr().out

    assert "[RAG开始]" in output
    assert "[RAG完成]" in output
    assert "citations=1" in output


def test_financial_search_service_can_use_postgres_adapter():
    retriever = FakeRetriever()
    adapter = PostgresRagSearchAdapter(retriever=retriever)
    service = FinancialSearchService(rag_search=adapter)

    result = service.search(
        query="What are the risks?",
        ticker="AAPL",
        curr_date="2025-01-31",
    )

    assert result.success is True
    assert result.source == "rag"
    assert result.data["rag"]["evidence"]["ticker"] == "AAPL"


def test_postgres_adapter_rejects_future_database_result():
    class FutureRetriever(FakeRetriever):
        def hybrid_search(self, query, *, ticker, as_of, top_k):
            return (make_hit(ticker=ticker, available_at=date(2025, 2, 1)),)

    adapter = PostgresRagSearchAdapter(retriever=FutureRetriever())
    with pytest.raises(ValueError, match="not available"):
        adapter("What are the risks?", "AAPL", date(2025, 1, 31))


def test_configured_rag_failure_is_not_reported_as_missing_configuration():
    """数据库已经注入但不可用时，错误码必须区别于未配置。"""
    service = FinancialSearchService(
        rag_search=lambda query, ticker, as_of: (_ for _ in ()).throw(
            ConnectionError("database unavailable")
        )
    )

    result = service.search(
        query="What are the risks?",
        ticker="AAPL",
        curr_date="2025-01-31",
    )

    assert result.success is False
    assert result.error_code == "RAG_ERROR"
    assert result.retryable is True
