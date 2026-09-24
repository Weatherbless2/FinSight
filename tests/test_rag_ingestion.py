"""R-04 下载和落盘逻辑的最小冒烟测试，不访问真实网络。"""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from tradingagents.rag.ingestion import (
    DocumentIngestionError,
    build_document_metadata,
    fetch_document,
    store_raw_document,
    write_failed_manifest,
)


def make_response(content=b"<html>report</html>"):
    response = Mock()
    response.content = content
    response.headers = {"content-type": "text/html; charset=utf-8"}
    return response


def test_fetch_build_and_store_document(tmp_path):
    """主路径：下载、计算哈希、写入原文和 JSON 清单。"""
    with patch(
        "tradingagents.rag.ingestion.requests.get",
        return_value=make_response(),
    ) as get:
        fetched = fetch_document("https://example.com/report.html")

    get.assert_called_once()
    metadata = build_document_metadata(
        fetched,
        document_id="aapl-2025q1-release",
        ticker="AAPL",
        document_type="earnings_release",
        title="AAPL earnings release",
        published_at=date(2025, 1, 31),
        available_at=date(2025, 1, 31),
    )
    stored = store_raw_document(fetched, metadata, tmp_path)

    assert stored.raw_path.read_bytes() == b"<html>report</html>"
    assert stored.manifest_path.read_text(encoding="utf-8").find('"status": "succeeded"') >= 0


def test_fetch_rejects_oversized_response():
    """关键边界：超过上限的原文不进入解析和索引流程。"""
    with patch(
        "tradingagents.rag.ingestion.requests.get",
        return_value=make_response(b"12345"),
    ), pytest.raises(DocumentIngestionError, match="exceeds max_bytes"):
        fetch_document("https://example.com/large.pdf", max_bytes=4)


def test_failed_manifest_is_written(tmp_path):
    """失败路径：网络错误也留下来源和错误类型，便于后续重试。"""
    error = DocumentIngestionError("download failed")
    path = write_failed_manifest(
        source_url="https://example.com/missing.html",
        output_dir=tmp_path,
        error=error,
        document_id="aapl-missing",
    )

    payload = path.read_text(encoding="utf-8")
    assert '"status": "failed"' in payload
    assert "download failed" in payload


def test_failed_manifest_uses_safe_hashed_filename(tmp_path):
    """失败边界：非法文档 ID 不能穿越 output_dir。"""
    path = write_failed_manifest(
        source_url="not-a-url",
        output_dir=tmp_path,
        error=ValueError("bad url"),
        document_id="../../outside",
    )

    assert path.parent == tmp_path
    assert path.name.startswith("failed-")
