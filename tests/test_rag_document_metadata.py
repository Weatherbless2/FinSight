"""R-01 文档契约的最小冒烟测试。"""

from datetime import date

import pytest
from pydantic import ValidationError

from tradingagents.rag.documents import (
    DocumentChunkMetadata,
    FinancialDocumentMetadata,
)


def make_document(**overrides):
    payload = {
        "document_id": "aapl-2025q1-10q",
        "ticker": "aapl",
        "document_type": "quarterly_report",
        "title": "AAPL quarterly report",
        "source_url": "https://example.com/aapl-2025q1.html",
        "source_hash": "A" * 64,
        "published_at": "2025-01-31",
        "available_at": "2025-01-31",
        "fiscal_period": "2025-Q1",
        "period_end": "2024-12-28",
        "language": "en-US",
    }
    payload.update(overrides)
    return FinancialDocumentMetadata.model_validate(payload)


def test_document_normalizes_ticker_and_applies_date_gate():
    """主路径验证：字段可解析，股票代码和来源哈希被规范化。"""
    document = make_document()

    assert document.ticker == "AAPL"
    assert document.source_hash == "a" * 64
    assert document.is_available_at(date(2025, 1, 30)) is False
    assert document.is_available_at(date(2025, 1, 31)) is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "file:///tmp/report.html"),
        ("source_hash", "not-a-sha256"),
        ("available_at", "2025-01-30"),
    ],
)
def test_document_rejects_unsafe_metadata(field, value):
    """关键边界验证：来源、哈希或时间线不可信时不得进入索引。"""
    with pytest.raises(ValidationError):
        make_document(**{field: value})


def test_chunk_metadata_keeps_citation_position_consistent():
    """片段位置验证：后续引用必须能按页码或字符区间回溯。"""
    chunk = DocumentChunkMetadata(
        chunk_id="aapl-2025q1-10q-0001",
        document_id="aapl-2025q1-10q",
        ordinal=0,
        section_title="Management Discussion",
        page_start=4,
        page_end=5,
        char_start=0,
        char_end=820,
        token_count=420,
    )

    assert chunk.page_end >= chunk.page_start
    assert chunk.char_end > chunk.char_start
