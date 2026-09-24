"""财报和公告进入 RAG 前的确定性元数据契约。"""

from __future__ import annotations

from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.dataflows.utils import safe_ticker_component

DocumentType = Literal[
    "annual_report",
    "quarterly_report",
    "earnings_release",
    "announcement",
    "earnings_call",
]


class FinancialDocumentMetadata(BaseModel):
    """一份财报、公告或业绩材料的父级元数据。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    document_type: DocumentType
    title: str = Field(min_length=1, max_length=512)
    source_url: str = Field(min_length=1, max_length=2048)
    source_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    published_at: date
    available_at: date
    fiscal_period: str | None = Field(default=None, max_length=32)
    period_end: date | None = None
    language: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z-]+$")

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        """限制 ID 字符，保证后续数据库主键和文件名都稳定。"""
        if not value[0].isalnum() or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
            for char in value
        ):
            raise ValueError("document_id contains unsupported characters")
        return value

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        """复用项目已有的路径安全规则，避免不可信股票代码进入索引键。"""
        return safe_ticker_component(value).upper()

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute http(s) URL")
        return value

    @field_validator("source_hash")
    @classmethod
    def normalize_source_hash(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def validate_publication_window(self):
        """公开时间不能早于文档标注的发布时间，避免时间线自相矛盾。"""
        if self.available_at < self.published_at:
            raise ValueError("available_at must be on or after published_at")
        return self

    def is_available_at(self, as_of: date) -> bool:
        """判断文档在某个历史分析日是否已经公开。"""
        return self.available_at <= as_of


class DocumentChunkMetadata(BaseModel):
    """文档片段的位置元数据；正文和向量在后续工单写入。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    chunk_id: str = Field(min_length=1, max_length=160)
    document_id: str = Field(min_length=1, max_length=128)
    ordinal: int = Field(ge=0)
    section_title: str = Field(min_length=1, max_length=512)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    token_count: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def validate_ranges(self):
        """保证引用位置有序，后续才能准确跳回原文。"""
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must be on or after page_start")
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self
