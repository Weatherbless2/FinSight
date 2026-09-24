"""RAG 浏览器演示的无网络单元测试。"""

from scripts.run_rag_demo import _expand_query
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
