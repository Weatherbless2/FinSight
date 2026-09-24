"""按章节、段落和表格边界切分 RAG 文档块。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from tradingagents.rag.documents import DocumentChunkMetadata
from tradingagents.rag.parsing import ParsedBlock, ParsedDocument

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\w\s]")
_SENTENCE_RE = re.compile(r"(?<=[.!?。！？；;])\s+")
DEFAULT_TARGET_TOKENS = 450
DEFAULT_MAX_TOKENS = 700
DEFAULT_OVERLAP_TOKENS = 70


@dataclass(frozen=True)
class DocumentChunk:
    """正文和 R-01 片段元数据的组合，供数据库适配器使用。"""

    metadata: DocumentChunkMetadata
    content: str


@dataclass(frozen=True)
class _TextPart:
    text: str
    section_title: str
    char_start: int
    char_end: int
    block_type: str


def estimate_token_count(text: str) -> int:
    """用无外部模型依赖的规则估算 token，供切分上限使用。"""
    return len(_TOKEN_RE.findall(text))


def _split_oversized_text(text: str, max_tokens: int) -> list[str]:
    if estimate_token_count(text) <= max_tokens:
        return [text.strip()]

    pieces: list[str] = []
    remaining = text.strip()
    while remaining:
        if estimate_token_count(remaining) <= max_tokens:
            pieces.append(remaining)
            break
        # URL、XBRL 标识符和数字密集文本的字符/token 比例变化很大，
        # 不能只按整体比例估算切点；二分搜索可以保证前缀不超过硬上限。
        low, high = 1, len(remaining)
        fitting_end = 1
        while low <= high:
            middle = (low + high) // 2
            if estimate_token_count(remaining[:middle]) <= max_tokens:
                fitting_end = middle
                low = middle + 1
            else:
                high = middle - 1
        cut = max(
            remaining.rfind(" ", 0, fitting_end),
            remaining.rfind("。", 0, fitting_end),
            remaining.rfind(".", 0, fitting_end),
            remaining.rfind("；", 0, fitting_end),
            remaining.rfind(";", 0, fitting_end),
        )
        if cut <= 0:
            cut = fitting_end
        piece = remaining[:cut].strip()
        if not piece:
            cut = min(len(remaining), fitting_end + 1)
            piece = remaining[:cut].strip()
        pieces.append(piece)
        remaining = remaining[cut:].strip()
    return pieces


def _split_paragraph(text: str, max_tokens: int) -> list[str]:
    """先按句子切，单句仍超长时再按字符/空格切。"""
    if estimate_token_count(text) <= max_tokens:
        return [text]
    sentences = [item.strip() for item in _SENTENCE_RE.split(text) if item.strip()]
    if len(sentences) <= 1:
        return _split_oversized_text(text, max_tokens)

    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and estimate_token_count(candidate) > max_tokens:
            pieces.extend(_split_oversized_text(current, max_tokens))
            current = sentence
        else:
            current = candidate
    if current:
        pieces.extend(_split_oversized_text(current, max_tokens))
    return pieces


def _block_spans(document: ParsedDocument) -> dict[int, tuple[int, int]]:
    """计算清洗后正文中的块区间，供引用回溯。"""
    spans: dict[int, tuple[int, int]] = {}
    cursor = 0
    for index, block in enumerate(document.blocks):
        start = cursor
        end = start + len(block.text)
        spans[index] = (start, end)
        cursor = end + 2
    return spans


def _make_chunk(
    *,
    document_id: str,
    ordinal: int,
    part: _TextPart,
) -> DocumentChunk:
    content = part.text.strip()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:10]
    metadata = DocumentChunkMetadata(
        chunk_id=f"{document_id}-{ordinal:04d}-{digest}",
        document_id=document_id,
        ordinal=ordinal,
        section_title=part.section_title,
        char_start=part.char_start,
        char_end=part.char_end,
        token_count=estimate_token_count(content),
    )
    return DocumentChunk(metadata=metadata, content=content)


def _table_parts(
    block: ParsedBlock,
    span: tuple[int, int],
    max_tokens: int,
) -> list[_TextPart]:
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    if not lines:
        return []
    prefix = lines[:2] if len(lines) > 1 else lines[:1]
    prefix_text = "\n".join(prefix)
    prefix_tokens = estimate_token_count(prefix_text)
    if prefix_tokens >= max_tokens:
        # SEC 内嵌 XBRL 可能把大量隐藏标识放在表格首行；
        # 此时优先保证硬上限，不能为了重复表头让 Chunk 超长。
        return [
            _TextPart(
                text=piece,
                section_title=block.section_title,
                char_start=span[0],
                char_end=span[1],
                block_type="table",
            )
            for piece in _split_oversized_text(block.text, max_tokens)
        ]
    rows = lines[2:] if len(lines) > 2 else []
    parts: list[_TextPart] = []
    current = list(prefix)
    for row in rows:
        candidate = "\n".join(current + [row])
        if len(current) > len(prefix) and estimate_token_count(candidate) > max_tokens:
            parts.append(
                _TextPart(
                    text="\n".join(current),
                    section_title=block.section_title,
                    char_start=span[0],
                    char_end=span[1],
                    block_type="table",
                )
            )
            current = list(prefix)
        if estimate_token_count("\n".join(current + [row])) > max_tokens:
            row_budget = max_tokens - prefix_tokens
            for piece in _split_oversized_text(row, max(1, row_budget)):
                parts.append(
                    _TextPart(
                        text="\n".join(prefix + [piece])
                        if estimate_token_count("\n".join(prefix + [piece])) <= max_tokens
                        else piece,
                        section_title=block.section_title,
                        char_start=span[0],
                        char_end=span[1],
                        block_type="table",
                    )
                )
            current = list(prefix)
        else:
            current.append(row)
    if current:
        parts.append(
            _TextPart(
                text="\n".join(current),
                section_title=block.section_title,
                char_start=span[0],
                char_end=span[1],
                block_type="table",
            )
        )
    return parts


def chunk_document(
    document: ParsedDocument,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[DocumentChunk, ...]:
    """按章节和块边界切分文档，返回稳定顺序的 Chunk。"""
    if not 1 <= target_tokens <= max_tokens:
        raise ValueError("target_tokens must be between 1 and max_tokens")
    spans = _block_spans(document)
    chunks: list[DocumentChunk] = []
    buffer: list[_TextPart] = []
    current_section = document.title

    def flush_buffer() -> None:
        if not buffer:
            return
        text = "\n\n".join(part.text for part in buffer)
        chunks.append(
            _make_chunk(
                document_id=document.document_id,
                ordinal=len(chunks),
                part=_TextPart(
                    text=text,
                    section_title=buffer[-1].section_title,
                    char_start=buffer[0].char_start,
                    char_end=buffer[-1].char_end,
                    block_type="paragraph",
                ),
            )
        )
        buffer.clear()

    for index, block in enumerate(document.blocks):
        span = spans[index]
        if block.block_type == "heading":
            flush_buffer()
            current_section = block.text
            continue

        if block.block_type == "table":
            flush_buffer()
            for part in _table_parts(block, span, max_tokens):
                chunks.append(
                    _make_chunk(
                        document_id=document.document_id,
                        ordinal=len(chunks),
                        part=part,
                    )
                )
            continue

        pieces = _split_paragraph(block.text, max_tokens)
        offset = 0
        for piece in pieces:
            start = block.text.find(piece, offset)
            if start < 0:
                start = offset
            end = start + len(piece)
            offset = end
            part = _TextPart(
                text=piece,
                section_title=current_section or block.section_title,
                char_start=span[0] + start,
                char_end=span[0] + end,
                block_type=block.block_type,
            )
            candidate = "\n\n".join(item.text for item in buffer + [part])
            if buffer and estimate_token_count(candidate) > max_tokens:
                flush_buffer()
            buffer.append(part)
            if estimate_token_count(candidate) >= target_tokens:
                flush_buffer()
    flush_buffer()
    return tuple(chunks)
