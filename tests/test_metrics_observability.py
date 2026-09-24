"""D-01 节点耗时 / D-02 总耗时与 P95 / E-04 步骤数 —— 确定性测试。

这些测试不调用任何真实 LLM 或数据供应商，完全离线、可重复运行，
属于第 1 层"确定性自动化测试"：验证观测统计公式本身是否正确。

用到的观测组件都在 tradingagents.observability 里：
- NodeTimer      ：记录每个节点的耗时序列与步骤数。
- wrap_graph_nodes：把 StateGraph 的每个节点包一层计时，行为不变。
- percentile/…   ：P50/P95/P99 等确定性统计。
"""
import time
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from tradingagents.observability import (
    NodeTimer,
    mean,
    median,
    p50,
    p95,
    p99,
    percentile,
    summarize,
    wrap_graph_nodes,
)


class _S(TypedDict):
    x: int
    y: int


def _sleep_node(delay: float):
    """返回一个「睡眠 delay 秒后原样返回状态」的节点函数（用来造真实耗时）。"""

    def node(state):
        time.sleep(delay)
        return state

    return node


# ---------------------------------------------------------------------------
# D-02：P50/P95/均值统计公式（确定性）
# ---------------------------------------------------------------------------


def test_percentile_linear_interpolation():
    # 5 个样本、中位数 = 第 3 个 = 3.0
    assert percentile([1, 2, 3, 4, 5], 50) == 3.0
    # P95 在 4 和 5 之间线性插值：rank = 0.95*4 = 3.8 -> 4*(1-0.8? ) ... 实际=4.8
    assert round(p95([1, 2, 3, 4, 5]), 6) == 4.8
    # 偶数样本中位数 = 中间两数平均
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert round(p50([1, 2, 3, 4]), 6) == 2.5


def test_summarize_fields_and_empty():
    s = summarize([1.0, 2.0, 3.0])
    assert s["count"] == 3
    assert s["mean"] == 2.0
    assert s["p50"] == 2.0
    # 空样本：统计函数必须稳定返回，不抛异常
    e = summarize([])
    assert e["count"] == 0
    assert e["p95"] == 0.0


def test_mean_median():
    assert mean([1, 2, 3, 4]) == 2.5
    assert median([1, 2, 3, 4, 5]) == 3.0
    assert p99([1, 2, 3, 4, 5]) > p95([1, 2, 3, 4, 5]) > p50([1, 2, 3, 4, 5])


# ---------------------------------------------------------------------------
# D-01 节点耗时 + E-04 步骤数（真实 StateGraph + 包裹计时）
# ---------------------------------------------------------------------------


def test_node_timing_and_step_count():
    """D-01：每个节点记录真实墙钟耗时；E-04：每次节点执行算一步。"""
    timer = NodeTimer()
    g = StateGraph(_S)
    g.add_node("NodeA", _sleep_node(0.02))
    g.add_node("NodeB", _sleep_node(0.03))
    g.add_edge(START, "NodeA")
    g.add_edge("NodeA", "NodeB")
    g.add_edge("NodeB", END)

    g = wrap_graph_nodes(g, timer)   # 无侵入包裹计时
    g.compile().invoke({"x": 0})

    # E-04：这条链跑过 2 个节点 -> 总步骤数 = 2
    assert timer.total_steps() == 2
    assert timer.execution_count("NodeA") == 1
    assert timer.execution_count("NodeB") == 1

    per = timer.per_node_summary()
    assert per["NodeA"]["count"] == 1
    assert per["NodeB"]["count"] == 1
    # D-01：真实耗时落在预期区间（0.02s / 0.03s）
    assert 0.01 < per["NodeA"]["mean"] < 0.06
    assert 0.02 < per["NodeB"]["mean"] < 0.07
    assert timer.total_time() > 0.0


def test_node_timer_repeat_records_full_series():
    """同一节点多次执行时，timer 保留完整耗时序列，供 D-02 做 P95 聚合。"""
    timer = NodeTimer()
    for _ in range(5):
        timer.record("ToolNode", 0.0, 0.1)
    series = timer.duration_series("ToolNode")
    assert len(series) == 5
    assert timer.execution_count("ToolNode") == 5
    assert timer.total_steps() == 5
    # 5 个恒为 0.1 的样本，P50/P95 都是 0.1
    got = timer.per_node_summary()["ToolNode"]
    assert got["p50"] == pytest.approx(0.1)
    assert got["p95"] == pytest.approx(0.1)


def test_wrap_graph_nodes_reports_start_step_before_completion():
    """实时输出要先看到步骤开始，再看到完成耗时。"""
    events = []
    timer = NodeTimer()
    g = StateGraph(_S)
    g.add_node("NodeA", lambda state: state)
    g.add_edge(START, "NodeA")
    g.add_edge("NodeA", END)

    wrap_graph_nodes(
        g,
        timer,
        on_start=lambda name, step: events.append(("start", name, step)),
        on_complete=lambda name, elapsed: events.append(("done", name)),
    )
    g.compile().invoke({"x": 0})

    assert events[0] == ("start", "NodeA", 1)
    assert events[1][0:2] == ("done", "NodeA")
