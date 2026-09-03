"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        history = state["investment_debate_state"].get("history", "")

        investment_debate_state = state["investment_debate_state"]

        prompt = f"""你是研究经理和辩论主持人。请批判性评估本轮辩论，并为交易员给出清晰、可执行的投资计划。

{instrument_context}

---

**评级标准**（必须且只能选择一个）：
- **Buy**：强烈认可看多论点，建议建立或增加仓位
- **Overweight**：观点偏积极，建议逐步增加敞口
- **Hold**：多空平衡，建议维持当前仓位
- **Underweight**：观点谨慎，建议减少仓位
- **Sell**：强烈认可看空论点，建议退出或避免持仓

只要辩论中的最强论据足以支持方向，就必须明确表态；只有证据确实均衡时才使用 Hold。

---

**辩论历史：**
{history}

{NO_EXTERNAL_TOOLS}""" + get_language_instruction()

        investment_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
