"""R-12-D PostgreSQL 检索适配器的无服务单元测试。"""

from datetime import date

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


def test_hydrate_hits_uses_parameterized_expanding_chunk_ids(monkeypatch):
    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "ticker": "AAPL",
                    "document_type": "annual_report",
                    "source_url": "https://example.com/doc",
                    "published_at": date(2025, 1, 1),
                    "available_at": date(2025, 1, 1),
                    "section_title": "Risk",
                    "content": "Revenue risk",
                }
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, params):
            assert "chunk_ids" in str(statement)
            assert params == {"chunk_ids": ["chunk-1"]}
            return FakeResult()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    retriever = PostgresRetriever(engine=FakeEngine(), embedding_provider=object())
    hydrated = retriever.hydrate_hits(["chunk-1", "chunk-1"])
    assert hydrated["chunk-1"].content == "Revenue risk"
