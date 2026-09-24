"""R-12-B：将 R-12-A 的 Chunk JSONL 导入 PostgreSQL。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.rag.postgres import (
    PostgresChunkRepository,
    create_postgres_engine,
    load_import_batch,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入真实金融文档 Chunk 到 PostgreSQL")
    parser.add_argument("--input-dir", default="data/processed_documents")
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy 连接串；未提供时读取 TRADINGAGENTS_DATABASE_URL 或 Compose 环境变量",
    )
    parser.add_argument("--source-name", help="ingestion_runs 中显示的来源名称")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验并统计 JSONL，不连接数据库",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)
    batch = load_import_batch(input_dir)
    source_name = args.source_name or str(input_dir)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "source_name": source_name,
                    "documents_seen": len(batch.documents),
                    "chunks_seen": len(batch.chunks),
                    "document_ids": [document.document_id for document in batch.documents],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    repository = PostgresChunkRepository(create_postgres_engine(args.database_url))
    stats = repository.import_batch(batch, source_name=source_name)
    print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
