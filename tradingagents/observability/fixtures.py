"""确定性数据 fixture：把工具层的 route_to_vendor 替换为本地返回。

为什么要做这件事（第 2 层真实运行）：
- 真实数据供应商（yfinance 等）有限流与波动。真实运行一旦被限流打断，
  "节点耗时 / 步骤数 / 总耗时"这些想量化的指标就拿不到了。
- 本模块把所有数据工具返回固定、可复现的 fixture 文本（不含任何外网调用），
  让整张 LangGraph 能以真实 LLM（gpt-5.5）快速、稳定地跑完，
  从而真实测量 D-01 节点耗时 / D-02 总耗时与 P95 / E-04 步骤数。

诚实边界：
- LLM 调用、节点编排、工具调用循环都是真实发生的（真实 API、真实耗钱）。
- 只有"数据内容"是 fixture。数据供应商本身的上限/重试/超时可靠性
  由第 1 层确定性测试（tests/test_metrics_tool_reliability.py）覆盖。
"""
from __future__ import annotations

from typing import Any

# 每个工具方法返回的 fixture 内容。内容刻意简短但结构像真数据，
# 让 LLM 有东西可写报告，又不会拖慢速度。
_FIXTURE_TEXT = {
    "get_stock_data": (
        "FIXTURE|get_stock_data|symbol=AAPL rows: "
        "2024-05-09 Open=170.0 High=173.0 Low=169.5 Close=172.5 Vol=55M "
        "2024-05-10 Open=172.6 High=175.2 Low=171.8 Close=174.1 Vol=60M"
    ),
    "get_indicators": (
        "FIXTURE|get_indicators|RSI=62.3 MACD=1.24 signal=0.87 SMA20=171.2 SMA50=168.4"
    ),
    "get_verified_market_snapshot": (
        "FIXTURE|snapshot|symbol resolved: AAPL | latest close 174.10 on 2024-05-10 "
        "| data window verified <= 2024-05-10"
    ),
    "get_news": (
        "FIXTURE|get_news|3 headlines: (1) strong AI demand (2) record buyback "
        "(3) supply chain improved. Sentiment leaning positive."
    ),
    "get_global_news": (
        "FIXTURE|get_global_news|macro: Fed holds rates; CPI decelerating; "
        "global equity sentiment neutral-positive."
    ),
    "get_insider_transactions": (
        "FIXTURE|get_insider_transactions|no material insider activity in window"
    ),
    "get_macro_indicators": (
        "FIXTURE|get_macro_indicators|CPI 3.2% GDP 2.1% unemployment 3.9%"
    ),
    "get_prediction_markets": (
        "FIXTURE|get_prediction_markets|P(fed cut in 6m)=0.62 P(recession in 12m)=0.18"
    ),
    "get_fundamentals": (
        "FIXTURE|get_fundamentals|Revenue 96B growth 9% NetIncome 26B EPS 1.72 "
        "PE 24.5 ROE 33% Debt/Equity 1.6"
    ),
    "get_balance_sheet": (
        "FIXTURE|get_balance_sheet|TotalAssets 332B TotalLiab 279B Equity 53B "
        "Cash 31B"
    ),
    "get_cashflow": (
        "FIXTURE|get_cashflow|OperatingCF 32B InvestingCF -9B FinancingCF -21B"
    ),
    "get_income_statement": (
        "FIXTURE|get_income_statement|Revenue 96B COGS 57B OpIncome 31B "
        "NetIncome 26B DilutedEPS 1.72"
    ),
    "fetch_stocktwits_messages": (
        "FIXTURE|StockTwits|Bullish: 2 (67%) Bearish: 1 (33%) "
        "Unlabeled: 0 Total: 3 messages"
    ),
    "fetch_reddit_posts": (
        "FIXTURE|Reddit|3 posts: sentiment mixed; no external network request"
    ),
}

_DEFAULT_FIXTURE = "FIXTURE|unknown_method|deterministic stub content"


def fixture_text(method: str) -> str:
    """返回某工具方法的 fixture 文本；未知方法给一个稳定占位。"""
    return _FIXTURE_TEXT.get(method, _DEFAULT_FIXTURE)


def _fixture_route(method: str, *args: Any, **kwargs: Any) -> str:
    """替换 route_to_vendor 的签名：method 名 + 任意参数 -> fixture 文本。"""
    return fixture_text(method)


def _fixture_snapshot(*args: Any, **kwargs: Any) -> str:
    """get_verified_market_snapshot 的构建函数不接受 method，单独占位。"""
    return fixture_text("get_verified_market_snapshot")


def install_fixture_data() -> None:
    """把各工具模块的 route_to_vendor / 构建函数替换为 fixture 返回。

    由于工具函数在调用时通过「模块全局名」查找 route_to_vendor，
    运行时替换模块属性即可生效，无需改动任何工具函数或核心图代码。
    """
    from tradingagents.agents.analysts import sentiment_analyst
    from tradingagents.agents.utils import (
        core_stock_tools,
        fundamental_data_tools,
        macro_data_tools,
        market_data_validation_tools,
        news_data_tools,
        prediction_markets_tools,
        technical_indicators_tools,
    )

    modules_with_route = [
        core_stock_tools,
        fundamental_data_tools,
        macro_data_tools,
        news_data_tools,
        prediction_markets_tools,
        technical_indicators_tools,
    ]
    for mod in modules_with_route:
        if hasattr(mod, "route_to_vendor"):
            mod.route_to_vendor = _fixture_route
    # 该工具不经过 route_to_vendor，而是用专门的构建函数
    market_data_validation_tools.build_verified_market_snapshot = _fixture_snapshot

    # 情绪分析师在模块导入时直接绑定了两个网络函数，不能只替换
    # tradingagents.dataflows.stocktwits/reddit 模块中的原函数；这里要替换
    # 分析师模块自己持有的引用，确保 fixture 运行真正不访问外部网络。
    sentiment_analyst.fetch_stocktwits_messages = (
        lambda ticker, limit=30: fixture_text("fetch_stocktwits_messages")
    )
    sentiment_analyst.fetch_reddit_posts = (
        lambda ticker, *args, **kwargs: fixture_text("fetch_reddit_posts")
    )
