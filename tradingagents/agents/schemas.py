"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# LLMs sometimes write a placeholder string ("None", "N/A", ...) into an optional
# numeric field instead of omitting it. Coerce those to None so the structured
# call validates instead of erroring (#1058). Pydantic still parses real numeric
# strings ("189.5") to float.
_NULLISH_FLOAT = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown"}


def _coerce_optional_float(value):
    if isinstance(value, str) and value.strip().lower() in _NULLISH_FLOAT:
        return None
    return value


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "投资建议。只能选择 Buy / Overweight / Hold / Underweight / Sell 之一。"
            "只有多空证据确实均衡时才使用 Hold，否则请选择论据更强的一方。"
        ),
    )
    rationale: str = Field(
        description=(
            "用对话式语言总结辩论双方的关键观点，并说明最终促成该建议的论据。"
        ),
    )
    strategic_actions: str = Field(
        description=(
            "给出交易员执行该建议的具体步骤，包括与评级一致的仓位管理指导。"
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="交易方向。只能选择 Buy / Hold / Sell 之一。",
    )
    reasoning: str = Field(
        description=(
            "基于分析师报告和研究计划说明采取该行动的理由，写 2-4 句。"
        ),
    )
    entry_price: float | None = Field(
        default=None,
        description="可选的入场价格目标，使用该标的的报价货币。",
    )
    stop_loss: float | None = Field(
        default=None,
        description="可选的止损价格，使用该标的的报价货币。",
    )
    position_sizing: str | None = Field(
        default=None,
        description="可选的仓位指导，例如“占组合 5%”。",
    )

    @field_validator("entry_price", "stop_loss", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "最终持仓评级。根据分析师辩论选择 Buy / Overweight / Hold / Underweight / Sell 之一。"
        ),
    )
    executive_summary: str = Field(
        description=(
            "简明行动计划，涵盖入场策略、仓位、关键风险位和时间周期，写 2-4 句。"
        ),
    )
    investment_thesis: str = Field(
        description=(
            "基于分析师辩论中的具体证据进行详细推理。如果 Prompt 中包含历史经验，请纳入分析；否则只依据当前分析。"
        ),
    )
    price_target: float | None = Field(
        default=None,
        description="可选的目标价格，使用该标的的报价货币。",
    )
    time_horizon: str | None = Field(
        default=None,
        description="可选的建议持有周期，例如“3-6 个月”。",
    )

    @field_validator("price_target", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sentiment Analyst
# ---------------------------------------------------------------------------


class SentimentBand(str, Enum):
    """Discrete sentiment direction produced by the Sentiment Analyst.

    Six tiers keep the signal granular enough to be actionable while remaining
    small enough for every provider to map reliably from its JSON output.
    """

    BULLISH = "Bullish"
    MILDLY_BULLISH = "Mildly Bullish"
    NEUTRAL = "Neutral"
    MIXED = "Mixed"
    MILDLY_BEARISH = "Mildly Bearish"
    BEARISH = "Bearish"


class SentimentReport(BaseModel):
    """Structured sentiment report produced by the Sentiment Analyst.

    Replaces the previous free-form prose output so downstream consumers
    (dashboards, audit logs, PDF renderers, other agents) can read
    ``overall_band`` and ``overall_score`` without maintaining fragile regex
    fallbacks that drift with every model release. ``narrative`` preserves the
    rich source-by-source analysis; ``render_sentiment_report`` prepends a
    deterministic header so the saved report stays human-readable.
    """

    overall_band: SentimentBand = Field(
        description=(
            "总体情绪方向。只能选择 Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish 之一。"
            "当来源方向明显不一致时使用 Mixed；只有所有来源确实沉默或没有明确观点时才使用 Neutral。"
        ),
    )
    overall_score: float = Field(
        ge=0.0,
        le=10.0,
        description=(
            "情绪强度数字，范围 0-10。0 表示极度看空，5 表示中性，10 表示极度看多。"
            "建议与 overall_band 一致：Bullish 约 6.5-10，Mildly Bullish 约 5.5-6.4，"
            "Neutral/Mixed 约 4.5-5.5，Mildly Bearish 约 3.5-4.4，Bearish 约 0-3.4。"
            "只强制校验 0-10 的范围。"
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description=(
            "根据数据质量和样本量评估置信度。某来源返回占位符或少于 5 条数据时使用 low；"
            "数据存在但较少时使用 medium；三个来源都有充分数据时使用 high。"
        ),
    )
    narrative: str = Field(
        description=(
            "完整的情绪报告，按以下顺序覆盖："
            "（1）逐来源分析并引用具体证据（消息数量、比例、代表性帖子）；"
            "（2）来源之间的背离和一致；（3）主导叙事主题；（4）数据揭示的催化剂和风险；"
            "（5）用 Markdown 表格总结关键情绪信号、方向、来源和支持证据。"
            "内容要有信息量和实质性，每一部分都应使用具体证据，为交易员提供新的信号。"
        ),
    )


def render_sentiment_report(report: SentimentReport) -> str:
    """Render a SentimentReport to the markdown shape the rest of the system expects.

    The structured header (band + score + confidence) is prepended to the
    narrative so the saved report is both human-readable and machine-parseable
    without regex.
    """
    return "\n".join([
        f"**Overall Sentiment:** **{report.overall_band.value}** "
        f"(Score: {report.overall_score:.1f}/10)",
        f"**Confidence:** {report.confidence.capitalize()}",
        "",
        report.narrative,
    ])
