"""SEC 财报发现、下载、切分、入库和向量化的一次增量任务。"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from tradingagents.rag.embeddings import OllamaEmbeddingProvider
from tradingagents.rag.postgres import (
    PostgresChunkRepository,
    create_postgres_engine,
    load_import_batch,
)
from tradingagents.rag.sec_filings import SECClient
from tradingagents.rag.sec_ingestion import ingest_sec_candidates


def run_sec_ingestion_pipeline(
    ticker: str,
    as_of: date,
    *,
    limit_per_form: int = 1,
) -> dict[str, Any]:
    """执行一次可重复的 SEC 增量同步；已存在文档由哈希和 ID 自动跳过。"""
    normalized_ticker = ticker.strip().upper()
    raw_dir = Path(os.getenv("TRADINGAGENTS_RAW_DOCUMENTS_DIR", "data/raw_documents"))
    processed_dir = Path(
        os.getenv("TRADINGAGENTS_PROCESSED_DOCUMENTS_DIR", "data/processed_documents")
    )
    reports_dir = Path(os.getenv("TRADINGAGENTS_INGESTION_REPORTS_DIR", "reports/ingestion"))

    client = SECClient(user_agent=os.getenv("SEC_USER_AGENT"))
    candidates = client.discover_filings(
        normalized_ticker,
        as_of=as_of,
        forms=("10-K", "10-Q", "8-K"),
        limit_per_form=limit_per_form,
    )
    downloaded = ingest_sec_candidates(
        candidates,
        output_dir=raw_dir,
        as_of=as_of,
        user_agent=client.user_agent,
    )

    # 复用已验证的解析与 Chunk 规则；输入按 ticker 筛选，避免重处理其他公司。
    from scripts.build_real_chunks import build_all_chunks

    chunk_summaries = build_all_chunks(
        raw_dir,
        processed_dir,
        ticker=normalized_ticker,
    )
    batch = load_import_batch(processed_dir)
    repository = PostgresChunkRepository(create_postgres_engine())
    import_stats = repository.import_batch(batch, source_name=f"sec:{normalized_ticker}")

    pending = repository.pending_embedding_chunks(limit=1000)
    embedding_written = 0
    if pending:
        provider = OllamaEmbeddingProvider()
        embedding_results = provider.embed_chunks(pending, batch_size=16)
        embedding_written = repository.update_embeddings(embedding_results)

    summary = {
        "ticker": normalized_ticker,
        "as_of": as_of.isoformat(),
        "candidates": len(candidates),
        "downloaded": downloaded.stored_count,
        "skipped_existing": downloaded.skipped_count,
        "filtered_future": downloaded.filtered_future_count,
        "download_failed": downloaded.failed_count,
        "chunk_documents": len(chunk_summaries),
        "documents_inserted": import_stats.documents_inserted,
        "chunks_inserted": import_stats.chunks_inserted,
        "chunks_skipped": import_stats.chunks_skipped,
        "embedding_rows_written": embedding_written,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{normalized_ticker.lower()}-{as_of.isoformat()}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary
