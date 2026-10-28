"""R-05 HTML 解析清洗的最小冒烟测试，不访问网络。"""

from datetime import datetime, timezone

import pytest

from tradingagents.rag.ingestion import FetchedDocument
from tradingagents.rag.parsing import (
    DocumentParseError,
    parse_document,
    parse_html_document,
    parse_pdf_document,
)


def make_fetched(html: str, content_type="text/html"):
    return FetchedDocument(
        source_url="https://example.com/report.html",
        content=html.encode("utf-8"),
        content_type=content_type,
        fetched_at=datetime.now(timezone.utc),
    )


def test_parser_keeps_sections_paragraphs_and_table_caption():
    """主路径：保留章节、正文、表格标题和 HTML 行定位。"""
    fetched = make_fetched(
        """
        <html><head><title>AAPL Report</title><style>.x{}</style></head>
        <body>
          <nav>Skip to main content</nav>
          <h1>Management Discussion</h1>
          <p>Revenue increased 20% and cash flow improved.</p>
          <table><caption>Revenue by segment</caption>
            <tr><th>Segment</th><th>Revenue</th></tr>
            <tr><td>Services</td><td>$10 million</td></tr>
          </table>
          <footer>All rights reserved</footer>
        </body></html>
        """
    )

    parsed = parse_html_document(fetched, document_id="aapl-2025q1")

    assert parsed.title == "AAPL Report"
    assert [block.block_type for block in parsed.blocks] == [
        "heading",
        "paragraph",
        "table",
    ]
    assert "Revenue by segment" in parsed.blocks[-1].text
    assert "$10 million" in parsed.text
    assert parsed.blocks[0].source_locator.startswith("html-line:")


def test_parser_removes_repeated_long_disclaimer():
    """边界验证：重复免责声明只保留一次，避免挤占后续 Chunk。"""
    disclaimer = (
        "This document contains a long forward-looking statement disclaimer "
        "that is repeated in the page footer and should be removed."
    )
    parsed = parse_html_document(
        make_fetched(
            f"<html><body><p>{disclaimer}</p><p>{disclaimer}</p>"
            "<p>Risk factor text.</p></body></html>"
        ),
        document_id="aapl-risk",
    )

    assert parsed.text.count("forward-looking statement") == 1
    assert "Risk factor text." in parsed.text


def test_parser_keeps_sec_leaf_div_body_and_section():
    """SEC 常用 div/span 承载正文，解析器不能只保留表格。"""
    parsed = parse_html_document(
        make_fetched(
            """<html><body>
            <div><span style="font-weight:700">ITEM 1. BUSINESS</span></div>
            <div><span>We design and sell electric vehicles.</span></div>
            <div><span style="font-weight:700">ITEM 1A. RISK FACTORS</span></div>
            <div><span>Demand and supply chain risks may affect results.</span></div>
            </body></html>"""
        ),
        document_id="tsla-sec",
    )

    assert [block.block_type for block in parsed.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "paragraph",
    ]
    assert parsed.blocks[1].section_title == "ITEM 1. BUSINESS"
    assert "supply chain risks" in parsed.blocks[3].text


def test_parser_discards_hidden_sec_xbrl_metadata():
    """隐藏的 XBRL 标识不是业务证据，不能进入 Chunk。"""
    parsed = parse_html_document(
        make_fetched(
            """<html><body>
            <div style="display:none">false 0001318605 us-gaap:RevenueMember</div>
            <div>Revenue increased during the year.</div>
            </body></html>"""
        ),
        document_id="tsla-xbrl",
    )

    assert len(parsed.blocks) == 1
    assert "us-gaap" not in parsed.text


def test_parser_discards_standalone_page_numbers():
    """目录中的独立页码没有检索价值，应从正文块中去掉。"""
    parsed = parse_html_document(
        make_fetched(
            "<html><body><p>Business discussion.</p><p>13</p></body></html>"
        ),
        document_id="sec-page-number",
    )

    assert parsed.text == "Business discussion."


@pytest.mark.parametrize("content_type", ["application/pdf", "application/octet-stream"])
def test_parser_rejects_non_html_content(content_type):
    """格式边界：PDF 解析留给后续工单，不能被 HTML 解析器静默处理。"""
    with pytest.raises(DocumentParseError, match="does not support"):
        parse_html_document(
            make_fetched("<html><body>text</body></html>", content_type),
            document_id="doc",
        )


def test_document_dispatch_keeps_html_path():
    parsed = parse_document(
        make_fetched("<html><body><p>Revenue increased.</p></body></html>"),
        document_id="dispatch",
    )

    assert parsed.parser == "html"
    assert parsed.blocks[0].source_locator.startswith("html-line:")


def test_pdf_parser_reports_missing_optional_runtime(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def missing_fitz(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("missing fitz")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_fitz)
    with pytest.raises(DocumentParseError, match="PyMuPDF"):
        parse_pdf_document(
            make_fetched("not a pdf", "application/pdf"),
            document_id="pdf",
        )
