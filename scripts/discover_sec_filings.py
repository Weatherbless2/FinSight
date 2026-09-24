"""R-14-A：发现截至指定日期可用的 SEC 财报和公告。"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from tradingagents.rag.sec_filings import SECClient, SECDiscoveryError


def main() -> int:
    parser = argparse.ArgumentParser(description="发现 SEC 公开财报候选")
    parser.add_argument("--ticker", required=True, help="股票代码，例如 TSLA")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--form",
        action="append",
        dest="forms",
        help="限定表单类型，可重复传入；默认 10-K、10-Q、8-K",
    )
    parser.add_argument("--limit-per-form", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--user-agent",
        default=os.getenv("SEC_USER_AGENT"),
        help="SEC 要求的身份标识；也可使用 SEC_USER_AGENT 环境变量",
    )
    args = parser.parse_args()

    try:
        filings = SECClient(user_agent=args.user_agent).discover_filings(
            args.ticker,
            as_of=args.as_of,
            forms=args.forms,
            limit_per_form=args.limit_per_form,
        )
    except (SECDiscoveryError, ValueError) as exc:
        parser.error(str(exc))

    payload = {
        "ticker": args.ticker.upper(),
        "as_of": args.as_of.isoformat(),
        "filing_count": len(filings),
        "filings": [item.model_dump(mode="json") for item in filings],
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
        print(f"发现完成：{args.output}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
