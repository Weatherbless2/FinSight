from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_global_news,
    get_instrument_context_from_state,
    get_language_instruction,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
)

# The date constraint is intentionally preserved in the rendered Chinese prompt;
# this marker documents the legacy "tool-call date ranges" contract.


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_news,
            get_global_news,
            get_macro_indicators,
            get_prediction_markets,
        ]

        system_message = (
            f"你是一名新闻研究员，负责分析最近一周的新闻和趋势。请撰写一份与交易和宏观经济相关的全球局势综合报告。可使用以下工具：get_news(ticker, start_date, end_date) 获取按代码筛选的{asset_label}新闻；get_global_news(curr_date, look_back_days, limit) 获取更广泛的宏观新闻；get_macro_indicators(indicator, curr_date, look_back_days) 从 FRED 的真实数据中验证宏观评论（例如 'cpi'、'core_pce'、'unemployment'、'fed_funds_rate'、'10y_treasury'、'yield_curve'）；get_prediction_markets(topic, limit) 获取前瞻事件的实时市场隐含概率（例如 'Fed rate cut'、'recession 2026'、地缘政治或行业事件）。请用具体证据给出可执行的交易洞察。"
            + """ 请在报告末尾附上一张 Markdown 表格，整理关键结论，确保清晰易读。"""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一名与其他助理协作的 AI 助手。请使用提供的工具推进任务。"
                    "如果无法完整回答也没关系，其他助理会接着处理；请先完成你能完成的部分。"
                    "如果你或其他助理已经给出 FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** 或最终交付物，"
                    "请在回答前加上 FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**，以便团队停止后续分析。"
                    "你可以使用以下工具：{tool_names}。"
                    "今天的日期是 {current_date}；所有分析和工具调用的日期范围都必须以它作为当前日期。{instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
