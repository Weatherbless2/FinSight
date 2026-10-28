"""R-12-B：PostgreSQL 入库适配器的无 Docker 契约测试。"""

from datetime import date

import pytest

from tradingagents.rag.postgres import (
    ChunkConflictError,
    ChunkRecord,
    DuplicateSourceHashError,
    build_import_batch,
    load_import_batch,
    postgres_url_from_env,
)


def _record(*, document_id: str = "demo", chunk_id: str = "demo-0000") -> ChunkRecord:
    return ChunkRecord(
        document={
            "document_id": document_id,
            "ticker": "AAPL",
            "document_type": "quarterly_report",
            "title": "Demo report",
            "source_url": "https://example.com/demo.html",
            "source_hash": "a" * 64,
            "published_at": date(2025, 1, 1),
            "available_at": date(2025, 1, 1),
            "language": "en",
        },
        chunk={
            "chunk_id": chunk_id,
            "document_id": document_id,
            "ordinal": 0,
            "section_title": "Summary",
            "char_start": 0,
            "char_end": 12,
            "token_count": 3,
        },
        content="Revenue increased.",
    )


def test_load_real_r12d_batch_has_expected_input_scale():
    """真实 R-12-D 评测语料应被完整读出，而不是只验证样例文件。"""
    root = __import__("pathlib").Path(__file__).parents[1] / "data" / "processed_documents"
    batch = load_import_batch(root)

    assert len(batch.documents) == 25
    assert len(batch.chunks) == 3027
    assert {document.ticker for document in batch.documents} == {
        "AAPL",
        "AMZN",
        "MSFT",
        "NVDA",
        "TSLA",
    }
    assert len({record.chunk.chunk_id for record in batch.chunks}) == 3027


def test_batch_deduplicates_identical_rows_but_rejects_conflicts():
    record = _record()
    batch = build_import_batch([record, record])
    assert len(batch.documents) == 1
    assert len(batch.chunks) == 1

    conflicting = record.model_copy(update={"content": "Revenue decreased."})
    with pytest.raises(ChunkConflictError):
        build_import_batch([record, conflicting])


def test_batch_rejects_same_source_hash_for_different_documents():
    with pytest.raises(DuplicateSourceHashError):
        build_import_batch([_record(document_id="one"), _record(document_id="two")])


def test_postgres_url_can_be_built_from_compose_environment(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "demo user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret/with-space")
    monkeypatch.setenv("POSTGRES_DB", "tradingagents")
    monkeypatch.setenv("POSTGRES_PORT", "55432")
    monkeypatch.delenv("TRADINGAGENTS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert postgres_url_from_env() == (
        "postgresql+psycopg://demo+user:secret%2Fwith-space@localhost:55432/tradingagents"
    )
