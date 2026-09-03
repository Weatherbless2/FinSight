from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)

        trader_decision = state["trader_investment_plan"]

        prompt = f"""你是激进型风险分析师，负责积极寻找高收益、高风险机会，强调大胆策略和竞争优势。评估交易员的决定或计划时，重点分析上行空间、增长潜力和创新收益，即使这些机会伴随较高风险。使用提供的市场数据和情绪分析强化论点，并逐条回应保守型和中性分析师的观点，用数据反驳其论据，指出他们可能错过的机会或过度保守的假设。

交易员的决定：
{trader_decision}

请论证为什么高收益视角是最佳路径，并参考以下资料：
{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
当前辩论历史：{history}
保守型分析师上一轮论点：{current_conservative_response}
中性分析师上一轮论点：{current_neutral_response}
如果其他观点尚未发言，请根据现有数据先提出自己的论点。请主动回应具体担忧，反驳逻辑弱点，强调承担风险的收益。重点是辩论和说服，不要只是罗列数据。请使用自然对话式表达，不要特殊格式。""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Aggressive Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
