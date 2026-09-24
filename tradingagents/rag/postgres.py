"""R-12-B：把已构建的金融文档 Chunk 幂等写入 PostgreSQL。"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, bindparam, create_engine, text

from tradingagents.rag.chunking import DocumentChunk
from tradingagents.rag.documents import DocumentChunkMetadata, FinancialDocumentMetadata
from tradingagents.rag.embeddings import ChunkEmbedding


class DocumentConflictError(ValueError):
    """同一主键对应的文档元数据发生变化时拒绝导入。"""


class ChunkConflictError(ValueError):
    """同一 Chunk ID 对应的正文或位置发生变化时拒绝导入。"""


class DuplicateSourceHashError(ValueError):
    """来源哈希已归属于另一份文档时拒绝导入。"""


class ChunkRecord(BaseModel):
    """JSONL 中一行文档元数据和 Chunk 正文的结构化表示。"""

    model_config = ConfigDict(extra="forbid")

    document: FinancialDocumentMetadata
    chunk: DocumentChunkMetadata
    content: str = Field(min_length=1)

    @classmethod
    def from_json_record(cls, record: dict[str, Any]) -> ChunkRecord:
        """校验导入行，并保证 Chunk 一定属于当前父文档。"""
        chunk_payload = record.get("chunk")
        if not isinstance(chunk_payload, dict):
            raise ValueError("chunk must be an object")
        chunk_metadata = chunk_payload.get("metadata")
        if not isinstance(chunk_metadata, dict):
            raise ValueError("chunk.metadata must be an object")
        parsed = cls.model_validate(
            {
                "document": record.get("document"),
                "chunk": chunk_metadata,
                "content": chunk_payload.get("content"),
            }
        )
        if parsed.chunk.document_id != parsed.document.document_id:
            raise ValueError(
                "chunk.document_id does not match document.document_id: "
                f"{parsed.chunk.document_id} != {parsed.document.document_id}"
            )
        return parsed

    def as_document_chunk(self) -> DocumentChunk:
        """转换成现有 RAG 类型，方便后续 Embedding 工单复用。"""
        return DocumentChunk(metadata=self.chunk, content=self.content)


@dataclass(frozen=True)
class ImportBatch:
    """一次导入中去重后的文档和 Chunk。"""

    documents: tuple[FinancialDocumentMetadata, ...]
    chunks: tuple[ChunkRecord, ...]


@dataclass(frozen=True)
class ImportStats:
    """数据库导入结果；inserted 和 skipped 用于验证幂等行为。"""

    run_id: UUID
    source_name: str
    documents_seen: int
    documents_inserted: int
    documents_skipped: int
    chunks_seen: int
    chunks_inserted: int
    chunks_skipped: int

    def as_dict(self) -> dict[str, Any]:
        """输出适合 CLI 和后续观测记录的普通字典。"""
        return {
            "run_id": str(self.run_id),
            "source_name": self.source_name,
            "documents_seen": self.documents_seen,
            "documents_inserted": self.documents_inserted,
            "documents_skipped": self.documents_skipped,
            "chunks_seen": self.chunks_seen,
            "chunks_inserted": self.chunks_inserted,
            "chunks_skipped": self.chunks_skipped,
        }


def iter_chunk_records(input_dir: str | Path) -> Iterator[ChunkRecord]:
    """按文件名和行号稳定读取所有 Chunk JSONL，跳过构建摘要文件。"""
    root = Path(input_dir)
    paths = sorted(root.glob("*.chunks.jsonl"))
    if not paths:
        raise FileNotFoundError(f"no *.chunks.jsonl files found in {root}")
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    raw_record = json.loads(line)
                    if not isinstance(raw_record, dict):
                        raise ValueError("JSONL row must be an object")
                    yield ChunkRecord.from_json_record(raw_record)
                except Exception as exc:  # noqa: BLE001 - 补充文件和行号
                    raise ValueError(f"invalid Chunk record {path}:{line_number}: {exc}") from exc


def build_import_batch(records: Iterable[ChunkRecord]) -> ImportBatch:
    """去重并检查批次内部冲突，避免把脏数据交给数据库。"""
    documents_by_id: dict[str, FinancialDocumentMetadata] = {}
    source_hash_to_id: dict[str, str] = {}
    chunks_by_id: dict[str, ChunkRecord] = {}

    for record in records:
        document_id = record.document.document_id
        previous_document = documents_by_id.get(document_id)
        if previous_document is not None and previous_document != record.document:
            raise DocumentConflictError(f"document metadata conflicts: {document_id}")
        previous_source = source_hash_to_id.get(record.document.source_hash)
        if previous_source is not None and previous_source != document_id:
            raise DuplicateSourceHashError(
                f"source_hash {record.document.source_hash} belongs to both "
                f"{previous_source} and {document_id}"
            )
        documents_by_id[document_id] = record.document
        source_hash_to_id[record.document.source_hash] = document_id

        previous_chunk = chunks_by_id.get(record.chunk.chunk_id)
        if previous_chunk is not None and previous_chunk != record:
            raise ChunkConflictError(f"chunk metadata or content conflicts: {record.chunk.chunk_id}")
        chunks_by_id[record.chunk.chunk_id] = record

    if not documents_by_id:
        raise ValueError("import batch must contain at least one Chunk")
    return ImportBatch(
        documents=tuple(documents_by_id.values()),
        chunks=tuple(chunks_by_id.values()),
    )


def load_import_batch(input_dir: str | Path) -> ImportBatch:
    """从 R-12-A 的输出目录读取并校验真实 Chunk。"""
    return build_import_batch(iter_chunk_records(input_dir))


def postgres_url_from_env() -> str:
    """读取显式连接串，或按 Compose 默认变量组装连接串。"""
    explicit = os.getenv("TRADINGAGENTS_DATABASE_URL") or os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    database = os.getenv("POSTGRES_DB", "tradingagents")
    user = quote_plus(os.getenv("POSTGRES_USER", "tradingagents"))
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", "tradingagents_dev_only"))
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"


def create_postgres_engine(database_url: str | None = None) -> Engine:
    """创建带连接健康检查的 SQLAlchemy Engine；真正连接在首次使用时发生。"""
    try:
        return create_engine(
            database_url or postgres_url_from_env(),
            pool_pre_ping=True,
            future=True,
        )
    except ModuleNotFoundError as exc:
        if exc.name == "psycopg":
            raise RuntimeError(
                "缺少 PostgreSQL 驱动，请先执行: .venv/bin/pip install -e '.[postgres]'"
            ) from exc
        raise


_INSERT_RUN = text(
    """
    INSERT INTO ingestion_runs
        (run_id, source_name, status, documents_seen)
    VALUES (:run_id, :source_name, 'running', :documents_seen)
    """
)
_UPDATE_RUN = text(
    """
    UPDATE ingestion_runs
    SET status = :status,
        documents_inserted = :documents_inserted,
        error_count = :error_count,
        finished_at = CURRENT_TIMESTAMP,
        error_message = :error_message
    WHERE run_id = :run_id
    """
)
_SELECT_DOCUMENT = text(
    """
    SELECT document_id, ticker, document_type, title, source_url, source_hash,
           published_at, available_at, fiscal_period, period_end, language
    FROM documents
    WHERE document_id = :document_id
    """
)
_SELECT_SOURCE = text(
    """
    SELECT document_id
    FROM documents
    WHERE source_hash = :source_hash
    """
)
_INSERT_DOCUMENT = text(
    """
    INSERT INTO documents
        (document_id, ticker, document_type, title, source_url, source_hash,
         published_at, available_at, fiscal_period, period_end, language)
    VALUES
        (:document_id, :ticker, :document_type, :title, :source_url, :source_hash,
         :published_at, :available_at, :fiscal_period, :period_end, :language)
    """
)
_SELECT_CHUNKS = text(
    """
    SELECT chunk_id, document_id, ordinal, section_title, page_start, page_end,
           char_start, char_end, token_count, content
    FROM document_chunks
    WHERE chunk_id IN :chunk_ids
    """
).bindparams(bindparam("chunk_ids", expanding=True))
_INSERT_CHUNK = text(
    """
    INSERT INTO document_chunks
        (chunk_id, document_id, ordinal, section_title, page_start, page_end,
         char_start, char_end, token_count, content)
    VALUES
        (:chunk_id, :document_id, :ordinal, :section_title, :page_start, :page_end,
         :char_start, :char_end, :token_count, :content)
    """
)


_SELECT_PENDING_EMBEDDING_CHUNKS = text(
    """
    SELECT chunk_id, document_id, ordinal, section_title, page_start, page_end,
           char_start, char_end, token_count, content
    FROM document_chunks
    WHERE embedding IS NULL
      AND embedding_status IN ('pending', 'failed')
    ORDER BY document_id, ordinal
    LIMIT :limit
    """
)

_UPDATE_EMBEDDING = text(
    """
    UPDATE document_chunks
    SET embedding = CASE
            WHEN :status = 'succeeded' THEN CAST(:vector AS vector)
            ELSE NULL
        END,
        embedding_provider = :provider,
        embedding_model = :model_name,
        embedding_version = :model_version,
        embedding_status = :status,
        embedding_error = :error,
        embedded_at = CASE WHEN :status = 'succeeded' THEN CURRENT_TIMESTAMP ELSE NULL END
    WHERE chunk_id = :chunk_id
    """
)


def _document_params(document: FinancialDocumentMetadata) -> dict[str, Any]:
    """把 Pydantic 文档契约转换成 SQL 参数，不拼接 SQL 字符串。"""
    return {
        "document_id": document.document_id,
        "ticker": document.ticker,
        "document_type": document.document_type,
        "title": document.title,
        "source_url": document.source_url,
        "source_hash": document.source_hash,
        "published_at": document.published_at,
        "available_at": document.available_at,
        "fiscal_period": document.fiscal_period,
        "period_end": document.period_end,
        "language": document.language,
    }


def _chunk_params(record: ChunkRecord) -> dict[str, Any]:
    """把一个 Chunk 的位置和正文映射到 document_chunks 列。"""
    metadata = record.chunk
    return {
        "chunk_id": metadata.chunk_id,
        "document_id": metadata.document_id,
        "ordinal": metadata.ordinal,
        "section_title": metadata.section_title,
        "page_start": metadata.page_start,
        "page_end": metadata.page_end,
        "char_start": metadata.char_start,
        "char_end": metadata.char_end,
        "token_count": metadata.token_count,
        "content": record.content,
    }


def _document_matches(row: Any, document: FinancialDocumentMetadata) -> bool:
    """比较数据库已有文档的业务字段，忽略数据库生成的时间字段。"""
    expected = _document_params(document)
    return all(row[key] == value for key, value in expected.items())


def _chunk_matches(row: Any, record: ChunkRecord) -> bool:
    """比较已有 Chunk 的正文和定位字段，防止同 ID 静默覆盖。"""
    expected = _chunk_params(record)
    return all(row[key] == value for key, value in expected.items())


class PostgresChunkRepository:
    """面向 R-03 表结构的最小导入仓储。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def import_batch(self, batch: ImportBatch, *, source_name: str) -> ImportStats:
        """在一个事务中写入文档和 Chunk，并记录成功或失败状态。"""
        run_id = uuid4()
        documents_inserted = 0
        documents_skipped = 0
        chunks_inserted = 0
        chunks_skipped = 0
        try:
            # 先单独提交 running 记录，后续业务事务回滚时仍能更新为 failed。
            with self.engine.begin() as connection:
                connection.execute(
                    _INSERT_RUN,
                    {
                        "run_id": run_id,
                        "source_name": source_name,
                        "documents_seen": len(batch.documents),
                    },
                )
            with self.engine.begin() as connection:
                for document in batch.documents:
                    row = connection.execute(
                        _SELECT_DOCUMENT,
                        {"document_id": document.document_id},
                    ).mappings().first()
                    source_row = connection.execute(
                        _SELECT_SOURCE,
                        {"source_hash": document.source_hash},
                    ).mappings().first()
                    if source_row and source_row["document_id"] != document.document_id:
                        raise DuplicateSourceHashError(
                            f"source_hash {document.source_hash} belongs to "
                            f"{source_row['document_id']}"
                        )
                    if row:
                        if not _document_matches(row, document):
                            raise DocumentConflictError(
                                f"document metadata conflicts in database: {document.document_id}"
                            )
                        documents_skipped += 1
                    else:
                        connection.execute(_INSERT_DOCUMENT, _document_params(document))
                        documents_inserted += 1

                chunk_ids = [record.chunk.chunk_id for record in batch.chunks]
                existing_rows = (
                    connection.execute(_SELECT_CHUNKS, {"chunk_ids": chunk_ids}).mappings().all()
                    if chunk_ids
                    else []
                )
                existing_by_id = {row["chunk_id"]: row for row in existing_rows}
                new_chunks: list[dict[str, Any]] = []
                for record in batch.chunks:
                    row = existing_by_id.get(record.chunk.chunk_id)
                    if row:
                        if not _chunk_matches(row, record):
                            raise ChunkConflictError(
                                f"chunk content or metadata conflicts in database: "
                                f"{record.chunk.chunk_id}"
                            )
                        chunks_skipped += 1
                    else:
                        new_chunks.append(_chunk_params(record))
                if new_chunks:
                    connection.execute(_INSERT_CHUNK, new_chunks)
                    chunks_inserted = len(new_chunks)
                connection.execute(
                    _UPDATE_RUN,
                    {
                        "run_id": run_id,
                        "status": "succeeded",
                        "documents_inserted": documents_inserted,
                        "error_count": 0,
                        "error_message": None,
                    },
                )
        except Exception as exc:
            # 失败状态单独开事务，避免业务事务回滚后丢掉导入诊断信息。
            try:
                with self.engine.begin() as connection:
                    connection.execute(
                        _UPDATE_RUN,
                        {
                            "run_id": run_id,
                            "status": "failed",
                            # 业务事务已经回滚，持久化插入数必须记为 0。
                            "documents_inserted": 0,
                            "error_count": 1,
                            "error_message": f"{type(exc).__name__}: {exc}"[:4000],
                        },
                    )
            except Exception:
                # 数据库本身不可达时保留原始异常，CLI 才能给出最直接的原因。
                pass
            raise

        return ImportStats(
            run_id=run_id,
            source_name=source_name,
            documents_seen=len(batch.documents),
            documents_inserted=documents_inserted,
            documents_skipped=documents_skipped,
            chunks_seen=len(batch.chunks),
            chunks_inserted=chunks_inserted,
            chunks_skipped=chunks_skipped,
        )

    def pending_embedding_chunks(self, *, limit: int = 1000) -> tuple[DocumentChunk, ...]:
        """读取还没有成功向量的 Chunk，供 Embedding 批处理脚本使用。"""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self.engine.connect() as connection:
            rows = connection.execute(
                _SELECT_PENDING_EMBEDDING_CHUNKS,
                {"limit": limit},
            ).mappings().all()
        return tuple(
            DocumentChunk(
                metadata=DocumentChunkMetadata(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    ordinal=row["ordinal"],
                    section_title=row["section_title"],
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                    char_start=row["char_start"],
                    char_end=row["char_end"],
                    token_count=row["token_count"],
                ),
                content=row["content"],
            )
            for row in rows
        )

    def update_embeddings(self, results: Sequence[ChunkEmbedding]) -> int:
        """将成功或失败结果批量写回，并保留模型追踪字段。"""
        if not results:
            return 0
        params = []
        for result in results:
            vector = None
            if result.vector is not None:
                vector = "[" + ",".join(str(value) for value in result.vector) + "]"
            params.append(
                {
                    "chunk_id": result.chunk_id,
                    "vector": vector,
                    "provider": result.provider,
                    "model_name": result.model_name,
                    "model_version": result.model_version,
                    "status": result.status,
                    "error": result.error,
                }
            )
        with self.engine.begin() as connection:
            connection.execute(_UPDATE_EMBEDDING, params)
        return len(params)
