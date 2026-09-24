"""R-12-D PostgreSQL 检索适配器的无服务单元测试。"""

from tradingagents.rag.postgres_retrieval import PostgresRetriever


def test_keyword_query_extracts_safe_ascii_prefix_terms():
    """中文问题混入英文财报术语时，转换结果不应带入 tsquery 操作符。"""
    query = PostgresRetriever._keyword_query("AAPL 最新年度报告 revenue risk factors")

    assert "annual" not in query
    assert "revenue:*" in query
    assert "risk:*" in query
    assert "factors:*" in query
    assert "|" in query
    assert "(" not in query
    assert ")" not in query
