"""R-11 受约束 Agentic Retrieval 的最小测试。"""

from datetime import date

from tradingagents.rag.agentic_retrieval import (
    AgenticRetrievalConfig,
    ConstrainedRetrievalRunner,
)
from tradingagents.rag.retrieval import RetrievalHit


def make_hit(chunk_id: str, content: str = "Revenue increased.") -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        document_id="doc-1",
        ticker="AAPL",
        document_type="quarterly_report",
        source_url="https://example.com/doc-1.html",
        published_at=date(2025, 1, 1),
        available_at=date(2025, 1, 1),
        section_title="Management Discussion",
        content=content,
        vector_score=0.9,
        keyword_score=1.0,
        fused_score=0.03,
        vector_rank=1,
        keyword_rank=1,
    )


def test_runner_stops_after_evidence_and_limits_chunks_per_round():
    """主路径：有证据时立即停止，并且单轮最多保留 6 个片段。"""
    calls = []
    hits = tuple(make_hit(f"chunk-{index}") for index in range(8))

    def retrieve(query):
        calls.append(query)
        return hits

    result = ConstrainedRetrievalRunner(retrieve).run("revenue")

    assert result.success is True
    assert result.stop_reason == "EVIDENCE_FOUND"
    assert result.queries_used == 1
    assert len(result.hits) == 6
    assert calls == ["revenue"]
    assert result.traces[0].hits_returned == 6


def test_runner_rewrites_once_when_first_query_has_no_evidence():
    """证据不足时允许一次改写，但仍受轮数和查询次数限制。"""
    calls = []

    def retrieve(query):
        calls.append(query)
        return () if query == "revenue" else (make_hit("risk-1", "Risk factors."),)

    result = ConstrainedRetrievalRunner(
        retrieve,
        query_rewriter=lambda query, round_index: "risk management",
    ).run("revenue")

    assert result.success is True
    assert result.stop_reason == "EVIDENCE_FOUND"
    assert calls == ["revenue", "risk management"]
    assert result.queries_used == 2
    assert len(result.traces) == 2


def test_runner_stops_duplicate_rewrite_and_does_not_loop():
    """关键边界：改写结果与历史 Query 相同，不能再次调用检索。"""
    calls = []

    def retrieve(query):
        calls.append(query)
        return ()

    result = ConstrainedRetrievalRunner(
        retrieve,
        query_rewriter=lambda query, round_index: "  REVENUE  ",
    ).run("revenue")

    assert result.success is False
    assert result.stop_reason == "DUPLICATE_QUERY"
    assert result.queries_used == 1
    assert calls == ["revenue"]


def test_runner_stops_on_context_budget_and_retrieval_error():
    """边界：上下文超预算或检索异常都必须有明确停止原因。"""
    budget_result = ConstrainedRetrievalRunner(
        lambda query: (make_hit("long-1", "x" * 200),),
        config=AgenticRetrievalConfig(max_context_chars=100),
    ).run("risk")
    assert budget_result.stop_reason == "CONTEXT_BUDGET"
    assert len(budget_result.context) <= 100

    error_result = ConstrainedRetrievalRunner(
        lambda query: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    ).run("risk")
    assert error_result.success is False
    assert error_result.stop_reason == "RETRIEVAL_ERROR"
    assert error_result.retryable is True


def test_runner_enforces_round_and_query_budgets():
    """预算边界：默认最多两轮，放宽轮数后仍最多三次查询。"""
    round_calls = []
    round_result = ConstrainedRetrievalRunner(
        lambda query: round_calls.append(query) or (),
        query_rewriter=lambda query, round_index: f"{query} next",
    ).run("risk")
    assert round_result.stop_reason == "MAX_ROUNDS"
    assert round_result.queries_used == 2
    assert len(round_calls) == 2

    query_calls = []
    query_result = ConstrainedRetrievalRunner(
        lambda query: query_calls.append(query) or (),
        query_rewriter=lambda query, round_index: f"{query} next",
        config=AgenticRetrievalConfig(max_rounds=8, max_queries=3),
    ).run("risk")
    assert query_result.stop_reason == "MAX_QUERIES"
    assert query_result.queries_used == 3
    assert len(query_calls) == 3
