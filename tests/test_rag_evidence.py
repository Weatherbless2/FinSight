"""R-09 证据包和日期校验的最小冒烟测试。"""

from dataclasses import replace
from datetime import date

import pytest

from tradingagents.rag.evidence import (
    EvidenceBundle,
    EvidenceValidationError,
    build_database_evidence_bundle,
    build_evidence_bundle,
)
from tradingagents.rag.retrieval import RetrievalHit


def make_hit(
    *,
    chunk_id: str = "chunk-1",
    ticker: str = "AAPL",
    available_at: date = date(2025, 1, 1),
    content: str = "Revenue increased.",
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        document_id="doc-1",
        ticker=ticker,
        document_type="quarterly_report",
        source_url="https://example.com/doc-1.html",
        published_at=date(2025, 1, 1),
        available_at=available_at,
        section_title="Management Discussion",
        content=content,
        vector_score=0.9,
        keyword_score=1.0,
        fused_score=0.03,
        vector_rank=1,
        keyword_rank=1,
    )


def make_indexed_chunk():
    from tradingagents.rag.chunking import DocumentChunk
    from tradingagents.rag.documents import DocumentChunkMetadata, FinancialDocumentMetadata
    from tradingagents.rag.retrieval import IndexedChunk

    document = FinancialDocumentMetadata(
        document_id="doc-1",
        ticker="AAPL",
        document_type="quarterly_report",
        title="AAPL Q1",
        source_url="https://example.com/doc-1.html",
        source_hash="1" * 64,
        published_at=date(2025, 1, 1),
        available_at=date(2025, 1, 1),
        language="en",
    )
    chunk = DocumentChunk(
        metadata=DocumentChunkMetadata(
            chunk_id="chunk-1",
            document_id="doc-1",
            ordinal=0,
            section_title="Management Discussion",
            char_start=0,
            char_end=18,
            token_count=3,
        ),
        content="Revenue increased.",
    )
    return IndexedChunk(document=document, chunk=chunk, embedding=(1.0,) + (0.0,) * 1535)


def test_build_evidence_bundle_keeps_traceable_source_and_excerpt():
    """主路径：命中必须能回到索引原文，并输出来源和章节。"""
    bundle = build_evidence_bundle(
        (make_hit(),),
        query="revenue",
        ticker="aapl",
        as_of=date(2025, 1, 31),
        indexed_chunks=(make_indexed_chunk(),),
    )

    assert bundle.ticker == "AAPL"
    assert bundle.citations[0].chunk_id == "chunk-1"
    assert bundle.citations[0].source_url == "https://example.com/doc-1.html"
    assert bundle.citations[0].text_excerpt == "Revenue increased."


def test_bundle_rejects_future_or_cross_ticker_citation():
    """关键边界：未来证据和跨股票证据都不能进入最终报告。"""
    with pytest.raises(ValueError, match="not available"):
        EvidenceBundle(
            query="revenue",
            ticker="AAPL",
            as_of=date(2025, 1, 31),
            citations=(
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "ticker": "AAPL",
                    "source_url": "https://example.com/doc-1.html",
                    "available_at": date(2025, 2, 1),
                    "section": "Management Discussion",
                    "text_excerpt": "Revenue increased.",
                },
            ),
        )

    with pytest.raises(ValueError, match="ticker"):
        EvidenceBundle(
            query="revenue",
            ticker="AAPL",
            as_of=date(2025, 1, 31),
            citations=(
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "ticker": "MSFT",
                    "source_url": "https://example.com/doc-1.html",
                    "available_at": date(2025, 1, 1),
                    "section": "Management Discussion",
                    "text_excerpt": "Revenue increased.",
                },
            ),
        )


def test_builder_rejects_missing_chunk_or_forged_text():
    """引用边界：不存在的 Chunk 或被篡改的正文必须被拒绝。"""
    indexed = make_indexed_chunk()
    with pytest.raises(EvidenceValidationError, match="does not exist"):
        build_evidence_bundle(
            (replace(make_hit(), chunk_id="missing"),),
            query="revenue",
            ticker="AAPL",
            as_of=date(2025, 1, 31),
            indexed_chunks=(indexed,),
        )

    with pytest.raises(EvidenceValidationError, match="text"):
        build_evidence_bundle(
            (replace(make_hit(), content="Forged text."),),
            query="revenue",
            ticker="AAPL",
            as_of=date(2025, 1, 31),
            indexed_chunks=(indexed,),
        )


def test_database_evidence_builder_rejects_future_hit():
    """数据库结果即使绕过内存索引，也必须再次执行日期边界校验。"""
    with pytest.raises(EvidenceValidationError, match="not available"):
        build_database_evidence_bundle(
            (make_hit(available_at=date(2025, 2, 1)),),
            query="revenue",
            ticker="AAPL",
            as_of=date(2025, 1, 31),
        )


def test_database_evidence_builder_rejects_cross_ticker_hit():
    """不能因为 SQL 或调用方传错参数，把另一只股票的证据交给 Agent。"""
    with pytest.raises(EvidenceValidationError, match="ticker"):
        build_database_evidence_bundle(
            (make_hit(ticker="MSFT"),),
            query="revenue",
            ticker="AAPL",
            as_of=date(2025, 1, 31),
        )
