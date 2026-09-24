"""R-09：检索证据包、来源和金融日期边界校验。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.rag.documents import FinancialDocumentMetadata
from tradingagents.rag.retrieval import IndexedChunk, RetrievalHit


class EvidenceValidationError(ValueError):
    """检索结果无法证明来源或日期安全时抛出的确定性错误。"""


class EvidenceCitation(BaseModel):
    """一条可以放进研究报告的最小证据引用。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    chunk_id: str = Field(min_length=1, max_length=160)
    document_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    source_url: str = Field(min_length=1, max_length=2048)
    available_at: date
    section: str = Field(min_length=1, max_length=512)
    text_excerpt: str = Field(min_length=1, max_length=12000)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        """证据中的股票代码和文档契约使用同一套规范化规则。"""
        return safe_ticker_component(value).upper()

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        """引用只能指向可回溯的 HTTP(S) 来源。"""
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute http(s) URL")
        return value


class EvidenceBundle(BaseModel):
    """一次检索对应的、可交给 Agent 的证据集合。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2048)
    ticker: str = Field(min_length=1, max_length=32)
    as_of: date
    citations: tuple[EvidenceCitation, ...]

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return safe_ticker_component(value).upper()

    @model_validator(mode="after")
    def validate_citations(self) -> EvidenceBundle:
        """再次检查整包证据，避免绕过构造函数直接注入跨股票或未来引用。"""
        if not self.citations:
            raise ValueError("evidence bundle must contain at least one citation")
        chunk_ids = [citation.chunk_id for citation in self.citations]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("evidence citations must have unique chunk_id values")
        for citation in self.citations:
            if citation.ticker != self.ticker:
                raise ValueError("evidence ticker does not match bundle ticker")
            if citation.available_at > self.as_of:
                raise ValueError("evidence is not available at the analysis date")
        return self


def _index_by_chunk_id(
    indexed_chunks: Mapping[str, IndexedChunk] | Sequence[IndexedChunk],
) -> dict[str, IndexedChunk]:
    if isinstance(indexed_chunks, Mapping):
        return dict(indexed_chunks)
    return {
        item.chunk.metadata.chunk_id: item
        for item in indexed_chunks
    }


def build_evidence_bundle(
    hits: Sequence[RetrievalHit],
    *,
    query: str,
    ticker: str,
    as_of: date,
    indexed_chunks: Mapping[str, IndexedChunk] | Sequence[IndexedChunk],
) -> EvidenceBundle:
    """只把能和索引原文逐字段对上的命中转换成证据包。"""
    normalized_query = query.strip()
    if not normalized_query:
        raise EvidenceValidationError("query must not be empty")
    normalized_ticker = safe_ticker_component(ticker).upper()
    source_index = _index_by_chunk_id(indexed_chunks)
    if not hits:
        raise EvidenceValidationError("cannot build evidence bundle without retrieval hits")

    citations: list[EvidenceCitation] = []
    seen_chunk_ids: set[str] = set()
    for hit in hits:
        if hit.chunk_id in seen_chunk_ids:
            raise EvidenceValidationError("duplicate citation chunk_id")
        seen_chunk_ids.add(hit.chunk_id)

        indexed = source_index.get(hit.chunk_id)
        if indexed is None:
            raise EvidenceValidationError(f"citation chunk does not exist: {hit.chunk_id}")
        document: FinancialDocumentMetadata = indexed.document
        chunk = indexed.chunk

        # 所有报告级引用都必须与真实索引记录逐项一致，不能相信模型回传的字段。
        if hit.ticker != normalized_ticker or document.ticker != normalized_ticker:
            raise EvidenceValidationError("citation ticker does not match requested ticker")
        if hit.document_id != document.document_id:
            raise EvidenceValidationError("citation document_id does not match index")
        if hit.source_url != document.source_url:
            raise EvidenceValidationError("citation source_url does not match index")
        if hit.available_at != document.available_at:
            raise EvidenceValidationError("citation available_at does not match index")
        if hit.section_title != chunk.metadata.section_title:
            raise EvidenceValidationError("citation section does not match index")
        if hit.content != chunk.content:
            raise EvidenceValidationError("citation text does not match index")
        if not document.is_available_at(as_of):
            raise EvidenceValidationError("citation is not available at the analysis date")

        citations.append(
            EvidenceCitation(
                chunk_id=hit.chunk_id,
                document_id=document.document_id,
                ticker=document.ticker,
                source_url=document.source_url,
                available_at=document.available_at,
                section=chunk.metadata.section_title,
                text_excerpt=chunk.content,
            )
        )

    return EvidenceBundle(
        query=normalized_query,
        ticker=normalized_ticker,
        as_of=as_of,
        citations=tuple(citations),
    )


def build_database_evidence_bundle(
    hits: Sequence[RetrievalHit],
    *,
    query: str,
    ticker: str,
    as_of: date,
) -> EvidenceBundle:
    """把 PostgreSQL 已返回的命中直接转换成可审计证据包。

    数据库检索结果已经同时携带文档元数据和 Chunk 正文，因此不需要再加载
    一份内存索引；这里仍然重新校验所有安全边界，防止未来文档、跨股票结果
    或不完整字段进入基本面 Agent 的上下文。
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise EvidenceValidationError("query must not be empty")
    normalized_ticker = safe_ticker_component(ticker).upper()
    if not hits:
        raise EvidenceValidationError("cannot build evidence bundle without retrieval hits")

    citations: list[EvidenceCitation] = []
    seen_chunk_ids: set[str] = set()
    for hit in hits:
        if hit.chunk_id in seen_chunk_ids:
            raise EvidenceValidationError("duplicate citation chunk_id")
        seen_chunk_ids.add(hit.chunk_id)
        if hit.ticker != normalized_ticker:
            raise EvidenceValidationError("citation ticker does not match requested ticker")
        if hit.available_at > as_of:
            raise EvidenceValidationError("citation is not available at the analysis date")
        if not hit.document_id or not hit.chunk_id or not hit.content.strip():
            raise EvidenceValidationError("database citation has incomplete fields")

        citations.append(
            EvidenceCitation(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                ticker=hit.ticker,
                source_url=hit.source_url,
                available_at=hit.available_at,
                section=hit.section_title,
                text_excerpt=hit.content,
            )
        )

    return EvidenceBundle(
        query=normalized_query,
        ticker=normalized_ticker,
        as_of=as_of,
        citations=tuple(citations),
    )
