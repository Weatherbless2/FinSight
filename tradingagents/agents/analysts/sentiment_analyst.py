"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Yahoo Finance news — which led LLMs to fabricate
Reddit/X/StockTwits content under prompt pressure (verified live).

The redesigned agent pre-fetches three complementary data sources before
the LLM is invoked and injects them into the prompt as structured blocks:

  1. News headlines     — Yahoo Finance (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                           user-labeled Bullish/Bearish sentiment tags
  3. Reddit posts        — r/wallstreetbets, r/stocks, r/investing

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern (json_schema for
OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic), falling
back to free-text generation for providers that lack native support, so
the sentiment header (band + score + confidence) is deterministic across
runs and providers instead of free-form per-model prose.

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch all three sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)
        stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
        reddit_block = fetch_reddit_posts(ticker)

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一名与其他助理协作的 AI 助手。"
                    "如果你或其他助理已经给出 FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** 或最终交付物，"
                    "请在回答前加上 FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**，以便团队停止后续分析。"
                    # No tool-calling here: the data is pre-fetched into the
                    # prompt, so tool-range wording would only invite a
                    # hallucinated tool call (#1130).
                    "今天的日期是 {current_date}，所有分析都必须以它作为当前日期。{instrument_context}"
                    " " + NO_EXTERNAL_TOOLS +
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    return f"""你是一名金融市场情绪分析师。你的任务是基于已经为你收集的三类互补数据，为 {ticker} 撰写覆盖 {start_date} 至 {end_date} 的综合情绪报告。

## 数据来源（已预先获取并放入本 Prompt）

### 新闻标题 —— Yahoo Finance，过去 7 天
机构视角，强调事实，是变化较慢的信号。

<start_of_news>
{news_block}
<end_of_news>

### StockTwits 消息 —— 以 cashtag 索引的散户交易平台
变化快速的信号。每条消息包含用户标注的情绪标签（Bullish / Bearish / no-label）和正文。

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit 帖子 —— r/wallstreetbets、r/stocks、r/investing（过去 7 天）
社区讨论。通过赞数和评论数衡量参与度。要考虑不同子版块的特点（r/wallstreetbets 往往更反向或兴奋，r/stocks 更审慎，r/investing 更偏长期）。

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## 数据分析方法（最佳实践）

1. **将 StockTwits 的 Bullish/Bearish 比例作为领先的散户情绪信号。** 70/30 表示中度看多；≥90/10 可能表示过度拥挤和反向风险；50/50 表示不确定。样本量很重要，必须依据实际消息数量，不能只看百分比。

2. **寻找不同来源之间的背离。** 如果新闻偏空而 StockTwits 极度看多，这种不一致本身就是信号：可能代表散户正在押注新闻尚未反映的论点，也可能代表散户追涨而机构保持谨慎。

3. **按参与度为 Reddit 帖子加权。** 一个获得 400 个赞、200 条评论的帖子代表社区关注；只有 3 个赞的帖子可能只是噪声。要阅读正文摘录，不能只看标题。

4. **区分观点和事件。** 新闻标题（例如“Nvidia announces $500M Corning deal”）是事件；StockTwits 帖子（例如“buying NVDA, this is going to moon”）是观点。两者都可以作为输入，但在结论中的权重应不同。

5. **识别反复出现的叙事主题。** 哪些话题在多个来源中持续出现？它们通常是驱动当前情绪的主导叙事。

6. **诚实说明数据限制。** 如果 StockTwits 只返回少量消息，或某个来源返回了“<unavailable>”占位符，情绪判断就不够稳健，必须在 `confidence` 字段和叙述中明确指出。如果某个子版块没有数据，也要说明。

7. **识别多个来源共同揭示的催化剂和风险**，例如即将发布的财报、产品发布、竞争威胁和宏观新闻。

8. **过去的情绪不具有确定的预测能力。** 请把结论表述为供交易员结合基本面和技术面权衡的信号，不要把它写成确定的价格预测。

## 输出字段

Fill the following fields:

 - **overall_band**：只能填写 Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish 之一。当来源方向明显不一致时使用 Mixed；只有所有来源确实沉默时才使用 Neutral。
 - **overall_score**：0（极度看空）到 10（极度看多）的数字，5 表示中性，并与 overall_band 保持一致。
 - **confidence**：根据数据质量和样本量填写 low / medium / high。
 - **narrative**：完整覆盖逐来源分析、背离、主导叙事、催化剂和风险，并附一张 Markdown 表格总结关键情绪信号（方向、来源、支持证据）。

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
