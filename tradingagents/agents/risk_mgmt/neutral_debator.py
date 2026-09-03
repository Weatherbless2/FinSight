from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)

        trader_decision = state["trader_investment_plan"]

        prompt = f"""你是中性风险分析师，负责提供平衡视角，权衡交易员决定或计划的潜在收益与风险。请综合评估上行和下行空间，同时考虑更广泛的市场趋势、经济变化和分散化策略。

交易员的决定：
{trader_decision}

请同时质疑激进型和保守型分析师，指出双方过度乐观或过度谨慎的地方，并利用以下资料支持适度、可持续的调整方案：
{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
当前辩论历史：{history}
激进型分析师上一轮论点：{current_aggressive_response}
保守型分析师上一轮论点：{current_conservative_response}
如果其他观点尚未发言，请根据现有数据先提出自己的论点。请批判性分析双方并逐条回应，说明适度风险策略如何兼顾增长潜力和极端波动保护。重点是辩论，不要只是陈述数据。请使用自然对话式表达，不要特殊格式。""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Neutral Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
