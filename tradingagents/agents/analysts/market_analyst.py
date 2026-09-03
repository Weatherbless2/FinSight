from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_indicators,
    get_instrument_context_from_state,
    get_language_instruction,
    get_stock_data,
    get_verified_market_snapshot,
)

# The date constraint is intentionally preserved in the rendered Chinese prompt;
# this marker documents the legacy "tool-call date ranges" contract.


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_stock_data,
            get_indicators,
            get_verified_market_snapshot,
        ]

        system_message = (
            """你是一名负责分析金融市场的交易助理。你的任务是根据当前市场状况或交易策略，从下面的列表中选择最相关的指标。最多选择 8 个能够互补且不重复的指标。各类指标及其说明如下：

移动平均线：
- close_50_sma：50 日简单移动平均线。用途：识别中期趋势方向，作为动态支撑/阻力。注意：具有滞后性，应与更快的指标结合。
- close_200_sma：200 日简单移动平均线。用途：确认长期市场趋势，识别金叉/死叉。注意：反应较慢，更适合战略判断而非频繁入场。
- close_10_ema：10 日指数移动平均线。用途：捕捉短期动量变化和潜在入场点。注意：震荡市场中噪声较多，应与长期均线配合。

MACD 指标：
- macd：MACD 主线，通过不同周期 EMA 的差值计算动量。用途：观察交叉和背离，识别趋势变化。低波动或横盘市场中应结合其他指标确认。
- macds：MACD 信号线，是 MACD 主线的 EMA 平滑线。用途：结合 MACD 主线交叉寻找交易信号，避免单独使用造成误判。
- macdh：MACD 柱状图，表示 MACD 主线与信号线之间的差距。用途：观察动量强弱并尽早发现背离，快速行情中要配合其他过滤条件。

动量指标：
- rsi：相对强弱指标，用于识别超买/超卖。可参考 70/30 阈值并观察背离；强趋势中 RSI 可能长期处于极端区域，必须结合趋势分析。

波动率指标：
- boll：布林带中轨，即 20 日 SMA。用途：作为价格运动的动态基准，应与上下轨结合判断突破或反转。
- boll_ub：布林带上轨，通常位于中轨上方 2 个标准差。可提示超买区域或突破区域，但强趋势中价格可能沿上轨运行。
- boll_lb：布林带下轨，通常位于中轨下方 2 个标准差。可提示潜在超卖区域，应结合其他分析避免误判反转。
- atr：平均真实波幅，用于衡量波动率。可用于设置止损和根据当前波动调整仓位，但它是反应型指标，应纳入更完整的风控方案。

成交量指标：
- vwma：成交量加权移动平均线。通过结合价格和成交量确认趋势；成交量异常时可能产生偏差，应结合其他成交量分析。

请选择信息互补的指标，避免重复（例如不要同时选择 rsi 和 stochrsi）。简要说明这些指标为什么适合当前市场环境。调用工具时必须使用上面列出的准确指标名称，否则调用会失败。请先调用 get_stock_data 获取生成指标所需的 CSV，再使用 get_indicators 和具体指标名称。

撰写最终报告前，必须调用 get_verified_market_snapshot 获取该代码在当前日期的验证快照，并将其作为所有精确 OHLCV、价格水平和指标数值的唯一依据。如果其他工具结果与验证快照冲突，请标记差异，不要自行编造一个“协调后”的数字。除非工具输出提供了具体日期和价格，否则不要声称完成历史验证、支撑/阻力位反弹或精确涨跌幅。

请写一份详细、严谨、有层次的趋势报告，用证据给出具体且可执行的交易洞察。"""
            + """ 请在报告末尾附上一张 Markdown 表格，整理报告中的关键结论，确保清晰易读。"""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一名与其他助理协作的 AI 助手。"
                    "请使用提供的工具推进任务。"
                    "如果无法完整回答也没关系，其他拥有不同工具的助理会接着处理；请先完成你能完成的部分。"
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
            "market_report": report,
        }

    return market_analyst_node
