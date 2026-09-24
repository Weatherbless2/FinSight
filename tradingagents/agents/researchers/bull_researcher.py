from tradingagents.agents.utils.agent_utils import (
    compact_for_prompt,
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

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

        prompt = f"""你是一名看多研究员，负责为投资 {target_label} 建立支持理由。请利用已有研究和数据，围绕增长潜力、竞争优势和积极市场指标，形成有证据支持的论点，并回应担忧、反驳看空观点。

重点关注：
- 增长潜力：市场机会、收入预期和扩张能力。
- 竞争优势：独特产品、品牌实力或市场地位。
- 积极指标：财务健康、行业趋势和近期利好新闻。
- 回应看空观点：用具体数据和严谨推理揭示看空论点的弱点。
- 互动辩论：直接回应看空研究员的观点，不要只是罗列数据。

可用资源：
{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻报告：{news_report}
{fundamentals_label}：{fundamentals_report}
辩论历史：{history}
看空研究员上一轮论点：{current_response}
请利用以上信息提出有说服力的看多论点，反驳看空观点，并进行动态辩论，展示看多立场的优势。
""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Bull Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
