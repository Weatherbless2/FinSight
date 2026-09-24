"""真实运行统计入口：跑一次或多次完整分析，采集真实指标。

这是"D-01/D-02/E-04"在第 2 层（真实运行）里的落地点：
    1. 用 TradingAgentsGraph 构建原始图（离线，不调 API）。
    2. 对 self.workflow 的节点做计时包裹，并重新编译成 self.graph。
    3. 每次运行前重置 NodeTimer，并把 StatsCallbackHandler 的计数做前后差，
       得到本轮的 LLM 调用次数 / 工具调用次数 / 令牌。
    4. 采集本轮：总耗时（D-02）、每个节点耗时（D-01）、步骤数（E-04）。
    5. run_many 提供多次运行的 P50/P95 聚合结果。

真实模型调用会花钱且有网络波动，因此把"真实运行"与"确定性测试"分开：
真实运行给出节点耗时 / 总耗时 / P95 / 步骤数这些"真实数字"；
边界、重试、超时、参数拦截这类要 100% 稳定复现的，交给确定性测试层。
"""
from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from cli.stats_handler import StatsCallbackHandler
from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import create_msg_delete
from tradingagents.graph.trading_graph import TradingAgentsGraph

from .fixtures import install_fixture_data
from .metrics import summarize
from .timer import NodeTimer, wrap_graph_nodes

_NODE_ACTIONS = {
    "Market Analyst": ("市场分析师", "分析行情和技术指标，并判断是否需要调用市场工具"),
    "tools_market": ("市场工具节点", "获取行情、技术指标和经过校验的市场快照"),
    "Msg Clear Market": ("清理市场上下文", "删除已消费的工具消息，准备进入下一个分析阶段"),
    "Social Analyst": ("情绪分析师", "分析社交媒体和投资者情绪"),
    "tools_social": ("情绪工具节点", "获取 StockTwits、Reddit 等情绪数据"),
    "Msg Clear Social": ("清理情绪上下文", "删除已消费的情绪工具消息"),
    "News Analyst": ("新闻分析师", "分析新闻、宏观因素和市场事件"),
    "tools_news": ("新闻工具节点", "获取新闻、宏观指标和相关市场信息"),
    "Msg Clear News": ("清理新闻上下文", "删除已消费的新闻工具消息"),
    "Fundamentals Analyst": ("基本面分析师", "分析财报、结构化基本面数据和财报 RAG 证据"),
    "tools_fundamentals": ("基本面工具节点", "获取财务数据或检索 PostgreSQL 财报 Chunk"),
    "Msg Clear Fundamentals": ("清理基本面上下文", "删除已消费的基本面工具消息"),
    "Bull Researcher": ("看多研究员", "根据各分析师报告提炼看多理由"),
    "Bear Researcher": ("看空研究员", "根据各分析师报告提炼风险和看空理由"),
    "Research Manager": ("研究经理", "综合多空观点，形成研究结论"),
    "Trader": ("交易员", "根据研究结论生成模拟交易计划"),
    "Aggressive Analyst": ("激进风险分析师", "从高风险、高收益角度复核交易计划"),
    "Conservative Analyst": ("保守风险分析师", "从本金保护角度复核交易计划"),
    "Neutral Analyst": ("中性风险分析师", "从客观证据角度复核交易计划"),
    "Portfolio Manager": ("组合经理", "汇总研究和风险意见，生成最终评级"),
}


def describe_node(name: str) -> tuple[str, str]:
    """返回终端展示用的中文节点名称和业务动作。"""
    return _NODE_ACTIONS.get(name, (name, "执行当前工作流节点"))


class InstrumentedRunner:
    """包装 TradingAgentsGraph，向其节点注入计时并采集真实运行指标。"""

    def __init__(
        self,
        config: dict[str, Any],
        selected_analysts=("market", "social", "news", "fundamentals"),
        fixture_data: bool = False,
        verbose: bool = False,
    ) -> None:
        """fixture_data=True 时，先把数据工具替换为确定性 fixture。

        这样真实运行不依赖 yfinance 等外网供应商（避免限流打断），
        LLM / 节点编排仍是真实调用，从而能稳定测出节点耗时与步骤数。
        verbose=True 时每个节点完成都会打印一行进度（真实运行观测用）。
        """
        self.timer = NodeTimer()
        self.stats = StatsCallbackHandler()
        self.verbose = verbose
        self._active_step = 0
        self.current_node_name: str | None = None
        if fixture_data:
            install_fixture_data()  # 运行时替换工具层数据源（模块级）
        # callbacks 会透传到 LLM 客户端，用于统计 LLM 调用与令牌。
        self.ta = TradingAgentsGraph(
            config=config,
            selected_analysts=selected_analysts,
            callbacks=[self.stats],
        )
        # 在编译前把每个节点包上计时；__init__ 里已经 compile 过一次，
        # 这里用包裹后的 workflow 重新编译，得到真正带计时的图。
        wrap_graph_nodes(
            self.ta.workflow,
            self.timer,
            on_start=self._on_node_start,
            on_complete=self._on_node_done,
        )
        self.ta.graph = self.ta.workflow.compile()

    def _on_node_start(self, name: str, step: int) -> None:
        """节点开始时说明当前业务动作，避免用户只看到内部节点名。"""
        self._active_step = step
        self.current_node_name = name
        if self.verbose:
            label, action = describe_node(name)
            print(
                f"[步骤 {step:02d}][开始] {label}（{name}） | {action}",
                flush=True,
            )

    def _on_node_done(self, name: str, elapsed: float) -> None:
        """节点完成时打印结果状态和耗时。"""
        if self.verbose:
            label, _ = describe_node(name)
            print(
                f"[步骤 {self._active_step:02d}][完成] {label}（{name}） | "
                f"耗时 {elapsed:.1f}s | 当前累计步骤 {self.timer.total_steps()}",
                flush=True,
            )

    def run_once(self, ticker: str, trade_date: str, asset_type: str = "stock") -> dict[str, Any]:
        """跑一次完整分析，返回本轮真实指标。

        decision 为 signal_processor 处理后的最终评级（Buy/Sell/Hold...）。
        total_seconds 是整张图从进入 propagate 到返回的真实墙钟时间（D-02）。
        """
        self.timer.reset()
        if self.verbose:
            print(
                f"[运行开始] ticker={ticker} | trade_date={trade_date} | "
                "正在启动 LangGraph 固定工作流",
                flush=True,
            )
        before = self.stats.get_stats()  # 取本轮开始前 LLM/工具/令牌累计值

        start = time.perf_counter()
        # 若 checkpoint 开启，propagate 内部会重新 compile（同样带着包裹），
        # 因为包裹是对 self.workflow 做的，compile 的来源一致。
        final_state, decision = self.ta.propagate(ticker, trade_date, asset_type=asset_type)
        total_seconds = time.perf_counter() - start

        after = self.stats.get_stats()
        result = {
            "ticker": ticker,
            "trade_date": trade_date,
            "decision": decision,
            "total_seconds": round(total_seconds, 4),
            "steps": self.timer.total_steps(),
            "node_summary": self.timer.per_node_summary(),
            "node_order": self.timer.node_names(),
            "llm_calls": after["llm_calls"] - before["llm_calls"],
            "tool_node_runs": after["tool_calls"] - before["tool_calls"],
            "tokens_in": after["tokens_in"] - before["tokens_in"],
            "tokens_out": after["tokens_out"] - before["tokens_out"],
        }
        if self.verbose:
            print(
                f"[运行完成] decision={decision} | 总耗时 {total_seconds:.1f}s | "
                f"步骤 {result['steps']} | LLM 调用 {result['llm_calls']} | "
                f"工具调用 {result['tool_node_runs']}",
                flush=True,
            )
        return result

    def run_fundamentals_only(
        self,
        ticker: str,
        trade_date: str,
        question: str,
        asset_type: str = "stock",
    ) -> dict[str, Any]:
        """只运行基本面 Agent 的局部工具循环，完成后立即结束。

        这是 RAG 验收专用入口，不改变生产 TradingAgentsGraph 的完整工作流：
        基本面分析师先决定是否调用工具，ToolNode 执行后回到分析师，分析师
        输出报告后直接 END。这样能独立观察“问题 -> 财报 RAG -> 报告”，
        不会继续进入 Bull Researcher 等后续高耗时节点。
        """
        self.timer.reset()
        self.current_node_name = None
        if self.verbose:
            print(
                f"[基本面专项开始] ticker={ticker} | trade_date={trade_date} | "
                f"question={question}",
                flush=True,
            )

        workflow = StateGraph(AgentState)
        workflow.add_node(
            "Fundamentals Analyst",
            create_fundamentals_analyst(
                self.ta.quick_thinking_llm,
                self.ta.financial_search_tool,
            ),
        )
        workflow.add_node("tools_fundamentals", self.ta.tool_nodes["fundamentals"])
        workflow.add_node("Msg Clear Fundamentals", create_msg_delete())
        workflow.add_edge(START, "Fundamentals Analyst")
        workflow.add_conditional_edges(
            "Fundamentals Analyst",
            self.ta.conditional_logic.should_continue_fundamentals,
            ["tools_fundamentals", "Msg Clear Fundamentals"],
        )
        workflow.add_edge("tools_fundamentals", "Fundamentals Analyst")
        workflow.add_edge("Msg Clear Fundamentals", END)
        wrap_graph_nodes(
            workflow,
            self.timer,
            on_start=self._on_node_start,
            on_complete=self._on_node_done,
        )

        state = self.ta.propagator.create_initial_state(
            ticker,
            trade_date,
            asset_type=asset_type,
            instrument_context=self.ta.resolve_instrument_context(ticker, asset_type),
        )
        state["messages"] = [
            HumanMessage(content=f"{ticker}：{question}")
        ]
        before = self.stats.get_stats()
        started = time.perf_counter()
        final_state = workflow.compile().invoke(
            state,
            config={
                "recursion_limit": self.ta.propagator.max_recur_limit,
                "callbacks": [self.stats],
            },
        )
        total_seconds = time.perf_counter() - started
        after = self.stats.get_stats()
        result = {
            "ticker": ticker,
            "trade_date": trade_date,
            "question": question,
            "fundamentals_report": final_state.get("fundamentals_report", ""),
            "total_seconds": round(total_seconds, 4),
            "steps": self.timer.total_steps(),
            "node_summary": self.timer.per_node_summary(),
            "node_order": self.timer.node_names(),
            "llm_calls": after["llm_calls"] - before["llm_calls"],
            "tool_node_runs": after["tool_calls"] - before["tool_calls"],
            "tokens_in": after["tokens_in"] - before["tokens_in"],
            "tokens_out": after["tokens_out"] - before["tokens_out"],
        }
        if self.verbose:
            print(
                f"[基本面专项完成] 总耗时 {total_seconds:.1f}s | 步骤 {result['steps']} | "
                f"LLM 调用 {result['llm_calls']} | 工具调用 {result['tool_node_runs']}",
                flush=True,
            )
        return result

    def run_many(self, ticker: str, trade_date: str, runs: int, asset_type: str = "stock") -> dict[str, Any]:
        """连续跑 runs 次，返回每轮的原始记录 + 聚合后的 P50/P95 指标。

        注意：真实模型调用是非确定性的，即使同 ticker/date，两次结果也可能不同，
        这正是 README 里说明的预期行为；我们只统计"耗时/步骤数/调用数"这类
        运行特征，不把 LLM 输出当作可复现的结果。
        """
        records = [self.run_once(ticker, trade_date, asset_type=asset_type) for _ in range(runs)]
        total_times = [r["total_seconds"] for r in records]
        step_counts = [r["steps"] for r in records]
        return {
            "runs": records,
            "total_seconds_summary": summarize(total_times),
            "steps_summary": summarize(step_counts),
        }
