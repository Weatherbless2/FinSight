"""RAG 浏览器演示的无网络单元测试。"""

from scripts.run_rag_demo import DemoService, _expand_query, _is_embedding_unavailable
from tradingagents.reporting_schema import structure_fundamentals_report


def test_demo_query_expands_chinese_financial_terms():
    query = _expand_query("TSLA 经营风险和管理层展望")

    assert "risk factors" in query
    assert "management" in query
    assert "outlook" in query


def test_fundamentals_report_is_structured_for_the_browser():
    report = structure_fundamentals_report(
        "FINAL TRANSACTION PROPOSAL: **HOLD**\n\n"
        "# TSLA 基本面\n\n结论内容\n\n"
        "## 财务质量\n\n收入和现金流内容\n\n"
        "## 主要风险\n\n价格战风险",
        ticker="TSLA",
        as_of="2025-03-01",
    )

    assert report.rating == "HOLD"
    assert [section.kind for section in report.sections] == [
        "summary",
        "detail",
        "metrics",
        "risk",
    ]
    assert report.raw_markdown.startswith("FINAL TRANSACTION PROPOSAL")


def test_embedding_outage_is_recognized_for_keyword_fallback():
    error = RuntimeError("Ollama embedding API failed after retries: [Errno 111] Connection refused")

    assert _is_embedding_unavailable(error) is True
    assert _is_embedding_unavailable(RuntimeError("database schema is invalid")) is False


def test_demo_service_falls_back_to_keyword_when_embedding_is_down():
    class FailingRetriever:
        def hybrid_search(self, *_args, **_kwargs):
            raise RuntimeError("Ollama embedding API failed after retries: connection refused")

        def keyword_search(self, *_args, **_kwargs):
            return ()

    service = DemoService.__new__(DemoService)
    service.retriever = FailingRetriever()
    service.online_fallback = None
    service.lock = __import__("threading").Lock()

    result = service.search(
        {
            "ticker": "TSLA",
            "as_of": "2025-03-01",
            "strategy": "hybrid",
            "top_k": 5,
            "question": "经营风险",
        }
    )

    assert result["requested_strategy"] == "hybrid"
    assert result["strategy"] == "keyword"
    assert result["fallback_reason"]
