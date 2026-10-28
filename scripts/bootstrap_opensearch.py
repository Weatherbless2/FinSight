"""Create the RAG OpenSearch projection and bulk-load processed Chunk JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from tradingagents.rag.opensearch import OpenSearchClient, build_chunk_projection


def iter_projections(paths: list[Path], *, tenant_id: str) -> Iterator[dict]:
    """Convert processed JSONL records into rebuildable index documents."""
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    document = record["document"]
                    chunk = record["chunk"]
                    metadata = chunk["metadata"]
                    content = chunk["content"]
                    yield build_chunk_projection(
                        chunk_id=metadata["chunk_id"],
                        document_id=document["document_id"],
                        ticker=document["ticker"],
                        document_type=document["document_type"],
                        section=metadata["section_title"],
                        content=content,
                        published_at=date.fromisoformat(document["published_at"]),
                        available_at=date.fromisoformat(document.get("available_at", document["published_at"])),
                        tenant_id=tenant_id,
                        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid processed Chunk at {path}:{line_number}: {exc}") from exc


def load_projection(client: OpenSearchClient, index: str, paths: list[Path], *, tenant_id: str, batch_size: int) -> int:
    """Create the index and write batches with chunk_id as the idempotency key."""
    client.create_index(index, index_version=index)
    batch: list[dict] = []
    count = 0
    for document in iter_projections(paths, tenant_id=tenant_id):
        batch.append(document)
        if len(batch) >= batch_size:
            client.bulk_upsert(index, batch)
            count += len(batch)
            batch.clear()
    if batch:
        client.bulk_upsert(index, batch)
        count += len(batch)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the TradeAgent OpenSearch RAG projection")
    parser.add_argument("paths", nargs="+", type=Path, help="processed Chunk JSONL files")
    parser.add_argument("--index", default=os.getenv("OPENSEARCH_INDEX", "rag-chunks-v1"))
    parser.add_argument("--tenant-id", default=os.getenv("TRADINGAGENTS_TENANT_ID", "default"))
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--url", default=os.getenv("OPENSEARCH_URL", "http://127.0.0.1:9200"))
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    client = OpenSearchClient(base_url=args.url)
    count = load_projection(client, args.index, args.paths, tenant_id=args.tenant_id, batch_size=args.batch_size)
    print(json.dumps({"index": args.index, "documents_indexed": count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
