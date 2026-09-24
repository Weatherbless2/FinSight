"""面向服务端和前端的结构化基本面报告契约。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReportRating = Literal["BUY", "HOLD", "SELL", "UNKNOWN"]


class ReportSection(BaseModel):
    """报告中的一个可独立展示的业务章节。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    kind: Literal["summary", "metrics", "risk", "outlook", "detail"] = "detail"


class FundamentalsReport(BaseModel):
    """基本面 Agent 的稳定输出；raw_markdown 只用于审计和展开查看。"""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    as_of: str
    rating: ReportRating
    summary: str
    sections: list[ReportSection]
    raw_markdown: str


_RATING_PATTERN = re.compile(
    r"FINAL\s+TRANSACTION\s+PROPOSAL\s*:\s*\**\s*(BUY|HOLD|SELL)\s*\**",
    re.IGNORECASE,
)
_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")


def _section_kind(title: str, index: int) -> str:
    """按标题把模型章节映射成前端需要的有限业务分类。"""
    normalized = title.lower()
    if index == 0 or any(word in normalized for word in ("结论", "summary", "摘要")):
        return "summary"
    if any(word in normalized for word in ("财务", "指标", "financial", "metric")):
        return "metrics"
    if any(word in normalized for word in ("风险", "risk")):
        return "risk"
    if any(word in normalized for word in ("展望", "outlook", "guidance")):
        return "outlook"
    return "detail"


def _split_sections(markdown: str) -> list[ReportSection]:
    """把 Markdown 标题切成页面卡片，正文保持原样避免损失模型信息。"""
    sections: list[tuple[str, list[str]]] = []
    current_title = "分析结果"
    current_lines: list[str] = []
    for line in markdown.splitlines():
        heading = _HEADING_PATTERN.match(line)
        if heading:
            if any(item.strip() for item in current_lines):
                sections.append((current_title, current_lines))
            current_title = heading.group(1).strip().strip("#")
            current_lines = []
        else:
            current_lines.append(line)
    if any(item.strip() for item in current_lines):
        sections.append((current_title, current_lines))

    result: list[ReportSection] = []
    for index, (title, lines) in enumerate(sections):
        content = "\n".join(lines).strip()
        if content:
            result.append(
                ReportSection(
                    title=title,
                    content=content,
                    kind=_section_kind(title, index),
                )
            )
    return result or [ReportSection(title="分析结果", content=markdown)]


def structure_fundamentals_report(
    markdown: str,
    *,
    ticker: str,
    as_of: str,
) -> FundamentalsReport:
    """将现有 Agent 文本包装成结构化契约，兼容旧模型和旧报告。"""
    normalized = markdown.strip()
    match = _RATING_PATTERN.search(normalized)
    rating: ReportRating = match.group(1).upper() if match else "UNKNOWN"  # type: ignore[assignment]
    sections = _split_sections(normalized)
    summary = sections[0].content[:800]
    return FundamentalsReport(
        ticker=ticker,
        as_of=as_of,
        rating=rating,
        summary=summary,
        sections=sections,
        raw_markdown=normalized,
    )
