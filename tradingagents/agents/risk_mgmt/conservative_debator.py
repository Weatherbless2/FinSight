from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_conservative_debator(llm):
    def conservative_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        conservative_history = risk_debate_state.get("conservative_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)

        trader_decision = state["trader_investment_plan"]

        prompt = f"""你是保守型风险分析师，首要目标是保护资产、降低波动并实现稳定可靠的增长。请优先考虑稳定性、安全性和风险缓释，仔细评估潜在损失、经济下行和市场波动。评估交易员计划时，重点审查其中的高风险因素，指出可能给组合带来的过度风险，并提出更谨慎、利于长期收益的替代方案。

交易员的决定：
{trader_decision}

请主动反驳激进型和中性分析师的观点，指出他们忽略的威胁或可持续性问题，并结合以下资料论证低风险调整方案：
{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
当前辩论历史：{history}
激进型分析师上一轮论点：{current_aggressive_response}
中性分析师上一轮论点：{current_neutral_response}
如果其他观点尚未发言，请根据现有数据先提出自己的论点。请质疑他们的乐观假设，强调可能被忽略的下行风险，逐条回应反驳点，说明保守立场为什么最能保护资产。重点是辩论和批判，不要只是罗列事实。请使用自然对话式表达，不要特殊格式。""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Conservative Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": conservative_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return conservative_node
