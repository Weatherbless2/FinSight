"""R-12-C：调用真实 Embedding API 并把向量写入 PostgreSQL。"""

from __future__ import annotations

import argparse
import json
import os
import time

from dotenv import load_dotenv

from tradingagents.rag.embeddings import OllamaEmbeddingProvider, OpenAIEmbeddingProvider
from tradingagents.rag.postgres import PostgresChunkRepository, create_postgres_engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为 PostgreSQL 中未嵌入 Chunk 生成真实向量")
    parser.add_argument("--database-url", help="SQLAlchemy 连接串")
    parser.add_argument(
        "--provider",
        choices=("ollama", "openai"),
        help="Embedding 服务；默认读取 TRADINGAGENTS_EMBEDDING_PROVIDER，未设置时使用 ollama",
    )
    parser.add_argument("--model", help="Ollama 模型名；默认读取 OLLAMA_EMBEDDING_MODEL")
    parser.add_argument("--limit", type=int, default=1000, help="最多处理的 Chunk 数")
    parser.add_argument("--batch-size", type=int, default=32, help="单次 API 请求的文本数")
    parser.add_argument("--max-retries", type=int, default=3, help="单批请求的最大重试次数")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="单次 HTTP 请求超时")
    parser.add_argument("--dry-run", action="store_true", help="只统计待处理数量，不调用 API")
    return parser.parse_args()


def main() -> int:
    load_dotenv(".env")
    args = parse_args()
    repository = PostgresChunkRepository(create_postgres_engine(args.database_url))
    chunks = repository.pending_embedding_chunks(limit=args.limit)
    print(json.dumps({"pending_chunks": len(chunks)}, ensure_ascii=False))

    if args.dry_run or not chunks:
        return 0

    provider_name = args.provider or os.getenv("TRADINGAGENTS_EMBEDDING_PROVIDER", "ollama")
    if provider_name == "ollama":
        provider = OllamaEmbeddingProvider(
            config=None,
            base_url=os.getenv("OLLAMA_EMBEDDING_BASE_URL"),
            max_retries=args.max_retries,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        provider = OpenAIEmbeddingProvider(
            max_retries=args.max_retries,
            timeout_seconds=args.timeout_seconds,
        )
    if args.model and provider_name == "ollama":
        provider.config.model_name = args.model
    started = time.perf_counter()
    results = provider.embed_chunks(chunks, batch_size=args.batch_size)
    written = repository.update_embeddings(results)
    elapsed_ms = (time.perf_counter() - started) * 1000
    succeeded = sum(result.status == "succeeded" for result in results)
    failed = len(results) - succeeded
    print(
        json.dumps(
            {
                "provider": provider.config.provider,
                "model": provider.config.model_name,
                "model_version": provider.config.model_version,
                "chunks_seen": len(results),
                "succeeded": succeeded,
                "failed": failed,
                "rows_written": written,
                "elapsed_ms": round(elapsed_ms, 2),
                "batch_size": args.batch_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
