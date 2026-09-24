"""R-07 Embedding Provider 的最小冒烟测试。"""

import pytest

from tradingagents.rag.chunking import DocumentChunk
from tradingagents.rag.documents import DocumentChunkMetadata
from tradingagents.rag.embeddings import (
    EmbeddingModelConfig,
    MockEmbeddingProvider,
)


def make_chunk(chunk_id: str, content: str) -> DocumentChunk:
    return DocumentChunk(
        metadata=DocumentChunkMetadata(
            chunk_id=chunk_id,
            document_id="aapl-2025q1",
            ordinal=0,
            section_title="Management Discussion",
            char_start=0,
            char_end=max(1, len(content)),
            token_count=max(1, len(content.split())),
        ),
        content=content,
    )


def test_mock_embedding_is_deterministic_and_matches_pgvector_dimension():
    """主路径：相同文本生成相同的 1536 维向量，并保留模型版本。"""
    provider = MockEmbeddingProvider()
    first = provider.embed_chunks((make_chunk("chunk-1", "Revenue increased."),))[0]
    second = provider.embed_chunks((make_chunk("chunk-2", "Revenue increased."),))[0]

    assert first.status == "succeeded"
    assert first.model_version == "v1"
    assert first.vector == second.vector
    assert len(first.vector or ()) == 1536


def test_model_dimension_must_match_database_contract():
    """关键边界：不允许生成无法写入 VECTOR(1536) 的向量。"""
    with pytest.raises(ValueError, match=r"VECTOR\(1536\)"):
        EmbeddingModelConfig(dimensions=768)


def test_failed_chunk_keeps_retryable_status():
    """失败边界：空正文转为失败记录，不影响调用方识别和重试。"""
    result = MockEmbeddingProvider().embed_chunks((make_chunk("chunk-empty", "   "),))[0]

    assert result.status == "failed"
    assert result.vector is None
    assert result.retryable is True
    assert "empty" in (result.error or "")
