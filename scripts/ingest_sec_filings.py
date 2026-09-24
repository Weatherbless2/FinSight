"""R-14-B：批量下载 R-14-A 发现的 SEC 财报。"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from tradingagents.rag.ingestion import DEFAULT_USER_AGENT
from tradingagents.rag.sec_ingestion import SECIngestionError, ingest_sec_discovery_file


def main() -> int:
    parser = argparse.ArgumentParser(description="批量下载 SEC 财报并保存原文清单")
    parser.add_argument("--input", required=True, type=Path, help="R-14-A 发现结果 JSON")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw_documents"))
    parser.add_argument("--summary", type=Path, help="导入汇总 JSON 输出路径")
    parser.add_argument("--as-of", type=date.fromisoformat, help="覆盖发现文件中的分析日期")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-bytes", type=int, default=25 * 1024 * 1024)
    parser.add_argument(
        "--user-agent",
        default=os.getenv("SEC_USER_AGENT") or DEFAULT_USER_AGENT,
        help="SEC 要求的身份标识；也可使用 SEC_USER_AGENT 环境变量",
    )
    args = parser.parse_args()

    try:
        summary = ingest_sec_discovery_file(
            args.input,
            output_dir=args.output_dir,
            as_of=args.as_of,
            user_agent=args.user_agent,
            timeout=args.timeout,
            max_bytes=args.max_bytes,
        )
    except (SECIngestionError, OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(
            json.dumps(summary.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"SEC 批量导入完成：候选 {summary.total_candidates} 条")
    print(f"成功保存：{summary.stored_count} 条")
    print(f"已存在跳过：{summary.skipped_count} 条")
    print(f"未来文档过滤：{summary.filtered_future_count} 条")
    print(f"下载失败：{summary.failed_count} 条")
    if args.summary:
        print(f"汇总清单：{args.summary}")
    return 2 if summary.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
