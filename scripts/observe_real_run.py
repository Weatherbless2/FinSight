"""真实运行观测脚本：用真实 LLM 跑一次/多次完整分析，输出真实指标 JSON。

这是第 2 层（真实运行）：真正调用 LLM 与数据供应商，产出
- D-01 每个节点的耗时
- D-02 总耗时（多次运行时含 P50/P95）
- E-04 步骤数
- LLM 调用次数 / 工具调用次数 / 输入输出令牌

用法：
    python scripts/observe_real_run.py --ticker NVDA --date 2024-05-10 --runs 1
    python scripts/observe_real_run.py --ticker AAPL --date 2024-05-10 --runs 5   # 多次运行出 P95

注意：真实模型调用非确定性，同 ticker/date 两次结果可能不同；且会消耗 API 额度。
为控制成本与时长，这里把辩论/风险轮数、新闻条数都调小（参数见 build_config）。
"""
from __future__ import annotations

import argparse
import json
import os

from tradingagents.default_config import DEFAULT_CONFIG as C
from tradingagents.observability import InstrumentedRunner


def build_config(
    *,
    deep_model: str = "gpt-5.5",
    quick_model: str = "gpt-5.5",
    max_retries: int = 0,
) -> dict:
    """构造一份「真实但低成本」的运行配置。

    - 模型：深度节点和快速节点默认都使用 gpt-5.5。
    - max_debate_rounds / max_risk_discuss_rounds 调成 0：大幅减少 LLM 调用，
      这样单次运行更快更便宜，但依然会完整走一遍「分析师 -> 研究员 -> 交易员
      -> 风险 -> 组合经理」的整张图，从而拿到真实节点耗时与步骤数。
    - 新闻条数调小：减少注入到上下文的数据量，也降低单次成本。
    """
    cfg = C.copy()
    cfg["llm_provider"] = "openai"
    cfg["deep_think_llm"] = deep_model
    cfg["quick_think_llm"] = quick_model
    # 跟随项目环境中的 OpenAI 兼容网关地址；当前项目使用
    # http://gptch.cloud/v1，不能在观测脚本中另外写死协议或域名。
    cfg["backend_url"] = os.getenv(
        "TRADINGAGENTS_LLM_BACKEND_URL",
        "https://gptch.cloud/v1",
    )
    cfg["openai_reasoning_effort"] = "low"
    # 代理网关的单次请求超时后，重试只会重复等待；观测脚本默认不重试。
    cfg["llm_max_retries"] = max_retries
    # 观测模式需要控制单个节点的输出上限，避免中转网关因长思考/长输出
    # 超过 120 秒；生产配置默认仍保持 None，不改变正式报告长度策略。
    cfg["llm_max_tokens"] = 1200
    cfg["max_debate_rounds"] = 0
    cfg["max_risk_discuss_rounds"] = 0
    cfg["news_article_limit"] = 5
    cfg["global_news_article_limit"] = 3
    cfg["checkpoint_enabled"] = False
    # 把记忆/缓存/结果指到临时目录：避免历史 pending 条目触发图开始前的
    # yfinance 结算（会限流拖慢），保证"图开始前的步骤"是纯本地、可复现的。
    import tempfile

    tmp = tempfile.mkdtemp(prefix="observe_run_")
    cfg["memory_log_path"] = f"{tmp}/trading_memory.md"
    cfg["data_cache_dir"] = f"{tmp}/cache"
    cfg["results_dir"] = f"{tmp}/results"
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="NVDA")
    ap.add_argument("--date", default="2024-05-10")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--deep-model", default="gpt-5.5")
    ap.add_argument("--quick-model", default="gpt-5.5")
    ap.add_argument("--max-retries", type=int, default=0)
    ap.add_argument(
        "--fundamentals-only",
        action="store_true",
        help="只运行基本面 Agent 的工具循环，生成报告后结束",
    )
    ap.add_argument(
        "--question",
        default="当前有哪些主要经营风险，管理层对后续经营有什么展望？",
        help="基本面专项模式使用的问题",
    )
    ap.add_argument(
        "--analysts",
        default="market,social,news,fundamentals",
        help="逗号分隔的分析师；下游研究/风险流程仍会继续执行",
    )
    ap.add_argument("--verbose", action="store_true", help="打印每个节点的完成进度")
    ap.add_argument("--debug", action="store_true", help="失败时打印完整 traceback")
    args = ap.parse_args()

    if args.max_retries < 0:
        ap.error("--max-retries 不能小于 0")
    selected_analysts = tuple(
        item.strip()
        for item in args.analysts.split(",")
        if item.strip()
    )
    allowed_analysts = {"market", "social", "news", "fundamentals"}
    invalid_analysts = set(selected_analysts) - allowed_analysts
    if not selected_analysts or invalid_analysts:
        ap.error(f"--analysts 包含无效值：{sorted(invalid_analysts)}")

    print(
        "[观测说明] 本次是真实 LLM + LangGraph 运行；数据工具使用本地 fixture，"
        "不访问 StockTwits/Reddit 外部接口，外部行情波动不会影响主链路计时。"
        "Ctrl+C 才是终止，Ctrl+Z 会挂起进程。",
        flush=True,
    )
    print(
        f"[运行参数] ticker={args.ticker} | trade_date={args.date} | runs={args.runs} | "
        f"deep_model={args.deep_model} | quick_model={args.quick_model} | "
        f"max_retries={args.max_retries} | analysts={','.join(selected_analysts)}",
        flush=True,
    )

    runner = InstrumentedRunner(
        config=build_config(
            deep_model=args.deep_model,
            quick_model=args.quick_model,
            max_retries=args.max_retries,
        ),
        selected_analysts=selected_analysts,
        fixture_data=True,
        verbose=args.verbose,
    )
    try:
        if args.fundamentals_only:
            if args.runs != 1:
                ap.error("--fundamentals-only 目前只支持 --runs 1")
            rec = runner.run_fundamentals_only(
                args.ticker,
                args.date,
                args.question,
            )
            print(json.dumps(rec, ensure_ascii=False, indent=2))
        elif args.runs == 1:
            rec = runner.run_once(args.ticker, args.date)
            print(json.dumps(rec, ensure_ascii=False, indent=2))
        else:
            out = runner.run_many(args.ticker, args.date, args.runs)
            print(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as exc:  # noqa: BLE001 - CLI 需要输出人类可读的失败摘要
        message = str(exc)
        print(
            f"[运行失败] 当前节点可能是：{runner.current_node_name or '未知'}",
            flush=True,
        )
        print(f"[错误类型] {type(exc).__name__}", flush=True)
        print(f"[错误信息] {message}", flush=True)
        if "524" in message or "Proxy Read Timeout" in message:
            print(
                "[原因判断] 中转网关等待上游模型超过 120 秒；不是 PostgreSQL 或 RAG 查询错误。",
                flush=True,
            )
            print(
                "[建议操作] 保持 gpt-5.5、--max-retries 0，"
                "并将 TRADINGAGENTS_RAG_TOP_K 调为 2 以减少上下文。",
                flush=True,
            )
        if args.debug:
            raise
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
