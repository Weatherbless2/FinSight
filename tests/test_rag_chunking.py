"""R-06 Chunk 切分的最小冒烟测试。"""

from tradingagents.rag.chunking import chunk_document, estimate_token_count
from tradingagents.rag.parsing import ParsedBlock, ParsedDocument


def make_document(*blocks):
    return ParsedDocument(
        document_id="aapl-2025q1",
        source_url="https://example.com/report.html",
        title="AAPL Report",
        blocks=tuple(
            ParsedBlock(
                ordinal=index,
                block_type=block_type,
                text=text,
                section_title=section,
                source_locator=f"html-line:{index + 1}",
            )
            for index, (block_type, text, section) in enumerate(blocks)
        ),
    )


def test_chunker_keeps_section_and_stable_metadata():
    """主路径：正文按章节聚合，Chunk ID 和顺序稳定。"""
    document = make_document(
        ("heading", "Management Discussion", "AAPL Report"),
        ("paragraph", "Revenue increased and cash flow improved.", "Management Discussion"),
        ("paragraph", "Margins remained stable during the quarter.", "Management Discussion"),
    )

    chunks = chunk_document(document, target_tokens=6, max_tokens=20)

    assert len(chunks) == 2
    assert all(chunk.metadata.section_title == "Management Discussion" for chunk in chunks)
    assert [chunk.metadata.ordinal for chunk in chunks] == [0, 1]
    assert chunks[0].metadata.chunk_id.startswith("aapl-2025q1-0000-")


def test_long_paragraph_never_exceeds_hard_limit():
    """关键边界：超长段落会拆分，单个 Chunk 不超过硬上限。"""
    long_text = " ".join(["Revenue increased because demand improved."] * 120)
    document = make_document(("paragraph", long_text, "Management Discussion"))

    chunks = chunk_document(document, target_tokens=40, max_tokens=70)

    assert len(chunks) > 1
    assert all(chunk.metadata.token_count <= 70 for chunk in chunks)
    assert all(chunk.metadata.char_end > chunk.metadata.char_start for chunk in chunks)


def test_table_is_kept_separate_and_repeats_header_when_split():
    """表格边界：表格不和正文混合，拆分时保留标题和表头。"""
    table = "Revenue by segment\nSegment | Revenue\n" + "\n".join(
        f"Segment {index} | {index} million" for index in range(30)
    )
    document = make_document(
        ("paragraph", "The company reported growth.", "Summary"),
        ("table", table, "Summary"),
    )

    chunks = chunk_document(document, target_tokens=20, max_tokens=30)
    table_chunks = [chunk for chunk in chunks if "Segment | Revenue" in chunk.content]

    assert len(table_chunks) > 1
    assert all(chunk.metadata.token_count <= 30 for chunk in table_chunks)
    assert all(chunk.content.startswith("Revenue by segment\nSegment | Revenue") for chunk in table_chunks)
    assert estimate_token_count(table_chunks[0].content) <= 30


def test_oversized_table_header_still_respects_hard_limit():
    """真实 SEC/XBRL 表头可能异常长，不能让它突破 Chunk 上限。"""
    huge_header = " ".join(["xbrl-identifier"] * 120)
    document = make_document(
        ("table", f"{huge_header}\nRevenue | 100", "Financial Statements")
    )

    chunks = chunk_document(document, target_tokens=20, max_tokens=30)

    assert chunks
    assert all(chunk.metadata.token_count <= 30 for chunk in chunks)
