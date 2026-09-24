"""手动导入一个公开财报或公告，供 R-04 学习和本地验证使用。"""

from __future__ import annotations

import argparse
from datetime import date

from tradingagents.rag.ingestion import (
    DEFAULT_USER_AGENT,
    build_document_metadata,
    fetch_document,
    store_raw_document,
    write_failed_manifest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保存公开金融文档和可追溯清单")
    parser.add_argument("--url", required=True, help="公开 HTTP(S) 文档地址")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--document-type",
        required=True,
        choices=[
            "annual_report",
            "quarterly_report",
            "earnings_release",
            "announcement",
            "earnings_call",
        ],
    )
    parser.add_argument("--title", required=True)
    parser.add_argument("--published-at", required=True, type=date.fromisoformat)
    parser.add_argument("--available-at", required=True, type=date.fromisoformat)
    parser.add_argument("--fiscal-period")
    parser.add_argument("--period-end", type=date.fromisoformat)
    parser.add_argument("--language", default="en")
    parser.add_argument("--output-dir", default="data/raw_documents")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        fetched = fetch_document(args.url, user_agent=args.user_agent)
        metadata = build_document_metadata(
            fetched,
            document_id=args.document_id,
            ticker=args.ticker,
            document_type=args.document_type,
            title=args.title,
            published_at=args.published_at,
            available_at=args.available_at,
            fiscal_period=args.fiscal_period,
            period_end=args.period_end,
            language=args.language,
        )
        stored = store_raw_document(fetched, metadata, args.output_dir)
    except Exception as exc:
        manifest = write_failed_manifest(
            source_url=args.url,
            output_dir=args.output_dir,
            error=exc,
            document_id=args.document_id,
        )
        print(f"导入失败，失败清单已写入: {manifest}")
        print(f"{type(exc).__name__}: {exc}")
        return 1

    print(f"导入成功: {stored.raw_path}")
    print(f"元数据清单: {stored.manifest_path}")
    print(f"SHA-256: {metadata.source_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
