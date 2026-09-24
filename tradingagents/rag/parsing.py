"""HTML 财报和公告的轻量解析与清洗。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from html import unescape
from typing import Literal

from parsel import Selector

from tradingagents.rag.ingestion import FetchedDocument

BlockType = Literal["heading", "paragraph", "list_item", "table"]

_SKIP_ANCESTORS = (
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "svg",
)
_NOISE_PATTERNS = (
    re.compile(r"skip to (main )?content", re.IGNORECASE),
    re.compile(r"privacy policy|cookie settings", re.IGNORECASE),
    re.compile(r"all rights reserved", re.IGNORECASE),
    re.compile(r"table of contents", re.IGNORECASE),
)
_SEC_SECTION_PATTERN = re.compile(
    r"^(?:PART\s+[IVX]+|ITEM\s+\d+[A-Z]?(?:\.|:)?(?:\s+.*)?)$",
    re.IGNORECASE,
)
_PAGE_NUMBER_PATTERN = re.compile(r"^\d{1,4}$")


class DocumentParseError(ValueError):
    """原文无法安全解析或清洗时抛出的错误。"""


@dataclass(frozen=True)
class ParsedBlock:
    """一个保留章节和 HTML 行位置的清洗后内容块。"""

    ordinal: int
    block_type: BlockType
    text: str
    section_title: str
    source_locator: str


@dataclass(frozen=True)
class ParsedDocument:
    """HTML 文档解析结果，供 R-06 Chunk 切分继续使用。"""

    document_id: str
    source_url: str
    title: str
    blocks: tuple[ParsedBlock, ...]

    @property
    def text(self) -> str:
        """按块顺序拼接正文，表格行保持换行。"""
        return "\n\n".join(block.text for block in self.blocks)


def _normalize_text(value: str) -> str:
    return " ".join(unescape(value).split())


def _is_noise(text: str) -> bool:
    return _PAGE_NUMBER_PATTERN.fullmatch(text) is not None or any(
        pattern.search(text) for pattern in _NOISE_PATTERNS
    )


def _is_garbled(text: str) -> bool:
    if not text:
        return True
    replacement_ratio = text.count("\ufffd") / len(text)
    return replacement_ratio > 0.05 or "\x00" in text


def _is_sec_heading(node, text: str) -> bool:
    """识别 SEC 常见的 div/span 章节标题，而不把普通正文当成标题。"""
    if _SEC_SECTION_PATTERN.match(text):
        return True
    styles = " ".join(
        node.xpath(".//@style").getall()
    ).lower()
    return "font-weight:700" in styles or "font-weight: 700" in styles


def _is_hidden(node) -> bool:
    """过滤 SEC 页面中 display:none 的 XBRL 辅助标识。"""
    styles = " ".join(node.xpath("ancestor-or-self::*[@style]/@style").getall()).lower()
    return "display:none" in styles or "display: none" in styles


def _table_text(node) -> str:
    caption = _normalize_text(" ".join(node.xpath("./caption//text()").getall()))
    rows = []
    for row in node.xpath("./thead/tr | ./tbody/tr | ./tfoot/tr | ./tr"):
        cells = [
            _normalize_text(" ".join(cell.xpath(".//text()").getall()))
            for cell in row.xpath("./th | ./td")
        ]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(" | ".join(cells))
    if caption:
        rows.insert(0, caption)
    return "\n".join(rows)


def parse_html_document(
    fetched: FetchedDocument,
    *,
    document_id: str,
) -> ParsedDocument:
    """解析 HTML，删除页面噪声并保留章节、表格和行位置。"""
    if fetched.content_type not in {"text/html", "application/xhtml+xml"}:
        raise DocumentParseError(
            f"HTML parser does not support content_type={fetched.content_type!r}"
        )
    if not fetched.content:
        raise DocumentParseError("document body is empty")

    html = fetched.content.decode("utf-8", errors="replace")
    selector = Selector(text=html)
    title = _normalize_text(" ".join(selector.xpath("//title//text()").getall()))
    if not title:
        title = _normalize_text(" ".join(selector.xpath("//h1[1]//text()").getall()))

    excluded = " or ".join(f"ancestor::{tag}" for tag in _SKIP_ANCESTORS)
    xpath = (
        "//body//*[self::h1 or self::h2 or self::h3 or self::h4 "
        "or self::h5 or self::h6 or self::p or self::li or self::table "
        "or (self::div and not(.//div or .//h1 or .//h2 or .//h3 "
        "or .//h4 or .//h5 or .//h6 or .//p or .//li or .//table))]"
        f"[not({excluded})]"
        "[not(ancestor::table)]"
    )
    nodes = selector.xpath(xpath)
    candidates: list[tuple[BlockType, str, str, str]] = []
    current_section = title

    for node in nodes:
        tag = node.root.tag.lower()
        if _is_hidden(node):
            continue
        block_type: BlockType
        text = _normalize_text(" ".join(node.xpath(".//text()").getall()))
        if tag.startswith("h") or (tag == "div" and _is_sec_heading(node, text)):
            block_type = "heading"
            if text:
                current_section = text
        elif tag == "table":
            block_type = "table"
            text = _table_text(node)
        elif tag == "li":
            block_type = "list_item"
            text = _normalize_text(" ".join(node.xpath(".//text()").getall()))
        else:
            block_type = "paragraph"
            text = _normalize_text(" ".join(node.xpath(".//text()").getall()))

        if not text or _is_noise(text) or _is_garbled(text):
            continue
        line = getattr(node.root, "sourceline", None) or 0
        candidates.append((block_type, text, current_section, f"html-line:{line}"))

    counts = Counter(text.lower() for _, text, _, _ in candidates)
    blocks = []
    for block_type, text, section, locator in candidates:
        # 长文本重复出现通常是页眉、页脚或免责声明；保留第一次出现。
        if counts[text.lower()] > 1 and len(text) >= 80:
            counts[text.lower()] -= 1
            continue
        blocks.append(
            ParsedBlock(
                ordinal=len(blocks),
                block_type=block_type,
                text=text,
                section_title=section or title or "未命名章节",
                source_locator=locator,
            )
        )

    if not blocks:
        raise DocumentParseError("no usable text blocks found in HTML document")
    return ParsedDocument(
        document_id=document_id,
        source_url=fetched.source_url,
        title=title or document_id,
        blocks=tuple(blocks),
    )
