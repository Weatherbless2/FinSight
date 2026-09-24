"""把公开导入的真实 HTML 文档解析并切分成可复用的 Chunk JSONL。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from tradingagents.rag.chunking import chunk_document
from tradingagents.rag.documents import FinancialDocumentMetadata
from tradingagents.rag.ingestion import FetchedDocument
from tradingagents.rag.parsing import parse_html_document


def process_manifest(
    manifest_path: Path,
    output_dir: Path,
    *,
    target_tokens: int = 450,
    max_tokens: int = 700,
) -> dict:
    """处理一份真实导入清单，输出 Chunk 文件和可审计摘要。"""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "succeeded":
        raise ValueError(f"manifest is not succeeded: {manifest_path}")

    metadata = FinancialDocumentMetadata.model_validate(manifest["metadata"])
    raw_path = manifest_path.with_suffix(".raw")
    content = raw_path.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != metadata.source_hash:
        raise ValueError(
            f"raw document hash mismatch for {metadata.document_id}: "
            f"expected {metadata.source_hash}, got {actual_hash}"
        )
    fetched = FetchedDocument(
        source_url=metadata.source_url,
        content=content,
        content_type=manifest["content_type"],
        fetched_at=datetime.fromisoformat(manifest["fetched_at"]),
    )

    parsed = parse_html_document(fetched, document_id=metadata.document_id)
    chunks = chunk_document(
        parsed,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = output_dir / f"{metadata.document_id}.chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            record = {
                "document": metadata.model_dump(mode="json"),
                "chunk": {
                    "metadata": chunk.metadata.model_dump(mode="json"),
                    "content": chunk.content,
                },
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    table_count = sum(block.block_type == "table" for block in parsed.blocks)
    heading_count = sum(block.block_type == "heading" for block in parsed.blocks)
    token_counts = [chunk.metadata.token_count for chunk in chunks]
    summary = {
        "document_id": metadata.document_id,
        "ticker": metadata.ticker,
        "source_url": metadata.source_url,
        "source_hash": metadata.source_hash,
        "raw_bytes": len(content),
        "parsed_blocks": len(parsed.blocks),
        "heading_blocks": heading_count,
        "table_blocks": table_count,
        "chunk_count": len(chunks),
        "min_chunk_tokens": min(token_counts) if token_counts else 0,
        "max_chunk_tokens": max(token_counts) if token_counts else 0,
        "average_chunk_tokens": (
            sum(token_counts) / len(token_counts) if token_counts else 0.0
        ),
        "chunks_path": str(chunks_path),
    }
    return summary


def build_all_chunks(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    target_tokens: int = 450,
    max_tokens: int = 700,
    ticker: str | None = None,
) -> tuple[dict, ...]:
    """按文件名稳定顺序处理成功清单，可选按股票代码筛选。"""
    input_root = Path(input_dir)
    output_root = Path(output_dir)
    manifests = sorted(input_root.glob("*.json"))
    if ticker:
        normalized_ticker = ticker.strip().upper()
        selected: list[Path] = []
        for path in manifests:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            metadata = payload.get("metadata", {})
            if str(metadata.get("ticker", "")).upper() == normalized_ticker:
                selected.append(path)
        manifests = selected
    summaries = tuple(
        process_manifest(
            path,
            output_root,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
        )
        for path in manifests
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "build-summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description="解析并切分真实公开金融文档")
    parser.add_argument("--input-dir", default="data/raw_documents")
    parser.add_argument("--output-dir", default="data/processed_documents")
    parser.add_argument("--target-tokens", type=int, default=450)
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--ticker", help="只处理指定股票的成功清单，例如 TSLA")
    args = parser.parse_args()

    summaries = build_all_chunks(
        args.input_dir,
        args.output_dir,
        target_tokens=args.target_tokens,
        max_tokens=args.max_tokens,
        ticker=args.ticker,
    )
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
