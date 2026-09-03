# TradingAgents/graph/reflection.py

from typing import Any


class Reflector:
    """Handles reflection on trading decisions."""

    def __init__(self, quick_thinking_llm: Any):
        """Initialize the reflector with an LLM."""
        self.quick_thinking_llm = quick_thinking_llm
        self.log_reflection_prompt = self._get_log_reflection_prompt()

    def _get_log_reflection_prompt(self) -> str:
        """Concise prompt for reflect_on_final_decision (Phase B log entries).

        Produces 2-4 sentences of plain prose — compact enough to be re-injected
        into future agent prompts without bloating the context window.
        """
        return (
            "你是一名交易分析师，现在已经知道结果，请复盘自己过去的交易判断。\n"
            "只写 2-4 句纯文本，不要使用项目符号、标题或 Markdown。\n\n"
            "按以下顺序覆盖：\n"
            "1. 方向判断是否正确？（引用 alpha 数值）\n"
            "2. 投资论点中的哪些部分成立或失败？\n"
            "3. 给下一次类似分析提出一条具体经验。\n\n"
            "内容要具体、简洁。你的输出会原样写入决策日志，"
            "并被未来的分析师重新读取，因此每个词都应有价值。"
        )

    def reflect_on_final_decision(
        self,
        final_decision: str,
        raw_return: float,
        alpha_return: float,
        benchmark_name: str = "SPY",
    ) -> str:
        """Single reflection call on the final trade decision with outcome context.

        Used by Phase B deferred reflection. The final_trade_decision already
        synthesises all analyst insights, so no separate market context is needed.
        ``benchmark_name`` is the label used for the alpha line (e.g. ``"SPY"``
        for US tickers, ``"^N225"`` for ``.T`` listings); defaults to SPY for
        callers that haven't been updated to thread the benchmark through.
        """
        messages = [
            ("system", self.log_reflection_prompt),
            (
                "human",
                (
                    f"绝对收益：{raw_return:+.1%}\n"
                    f"相对 {benchmark_name} 的 Alpha（Alpha vs {benchmark_name}: {alpha_return:+.1%}）：{alpha_return:+.1%}\n\n"
                    f"最终决策：\n{final_decision}"
                ),
            ),
        ]
        return self.quick_thinking_llm.invoke(messages).content
