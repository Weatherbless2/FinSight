from tradingagents.agents.utils.agent_utils import (
    compact_for_prompt,
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = compact_for_prompt(state["market_report"], max_chars=600)
        sentiment_report = compact_for_prompt(state["sentiment_report"], max_chars=600)
        news_report = compact_for_prompt(state["news_report"], max_chars=600)
        fundamentals_report = compact_for_prompt(state["fundamentals_report"], max_chars=600)
        instrument_context = get_instrument_context_from_state(state)
        asset_type = state.get("asset_type", "stock")
        target_label = "stock" if asset_type == "stock" else "asset"
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )

        prompt = f"""你是一名看空研究员，负责论证不应投资 {target_label}。请围绕风险、挑战和负面指标提出严谨论点，利用已有研究和数据揭示潜在下行空间，并有效反驳看多观点。

重点关注：
- 风险与挑战：市场饱和、财务不稳定或宏观经济威胁等可能拖累表现的因素。
- 竞争弱点：市场地位较弱、创新能力下降或竞争对手威胁。
- 负面指标：财务数据、市场趋势或近期不利新闻。
- 回应看多观点：用具体数据和严谨推理揭示看多论点的弱点或过度乐观假设。
- 互动辩论：直接回应看多研究员的观点，不要只是罗列事实。

可用资源：
{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻报告：{news_report}
{fundamentals_label}：{fundamentals_report}
辩论历史：{history}
看多研究员上一轮论点：{current_response}
请利用以上信息提出有说服力的看空论点，反驳看多观点，并进行动态辩论，展示投资 {target_label} 的风险和弱点。
""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
