from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_fundamentals_analyst(llm, financial_search_tool=None):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
        ]
        if financial_search_tool is not None:
            tools.append(financial_search_tool)

        system_message = (
            "你是一名基本面研究员，负责分析公司截至当前日期的基本面信息。请综合研究财务文件、公司概况、核心财务数据和历史财务表现，写一份简洁但可执行的报告，为交易员提供决策依据。控制在 800 到 1200 字以内，只保留有证据支持的关键结论。"
            + "请在报告末尾附上一张 Markdown 表格，整理关键结论，确保清晰易读。"
            + "可使用以下工具：`get_fundamentals` 获取综合公司分析，`get_balance_sheet` 获取资产负债表，`get_cashflow` 获取现金流量表，`get_income_statement` 获取利润表。"
            + (
                "可使用 `search_financial_documents` 查询财报、公告和管理层表述；"
                "涉及风险、原因、展望等定性问题时优先使用它。"
                if financial_search_tool is not None
                else ""
            )
            + get_language_instruction(),
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
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
