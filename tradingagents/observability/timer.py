"""节点级计时器 + 无侵入包裹图节点（D-01 节点耗时、E-04 步骤数）。

面试题：如何度量每个智能体 / 工具节点的耗时？（D-01）
回答：在 StateGraph 编译之前，把每个节点包裹一层"记录开始/结束时间戳"
的函数。节点原本的行为不变，只是额外把耗时写进 NodeTimer。这样既拿到
每个节点的真实墙钟时间，又不改动任何节点内部逻辑（所以 609 项回归不变）。

面试题：一次分析要经过多少 Agent / 工具 / 辩论节点？（E-04）
回答：NodeTimer 每执行一次节点就计数一次，即"步骤数"。整张图跑完，
total_steps 就是这一次分析经历的总节点数。
"""
from __future__ import annotations

import threading
import time
from typing import Any

from langchain_core.runnables import RunnableLambda

from .metrics import summarize


class NodeTimer:
    """线程安全的节点级计时器与步骤计数器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # node_name -> 每次执行的耗时（秒）列表
        self._durations: dict[str, list[float]] = {}
        # node_name -> 执行次数
        self._exec_counts: dict[str, int] = {}
        # 节点开始时就分配步骤号，便于实时日志在节点执行过程中显示进度。
        self._step_sequence = 0

    def reset(self) -> None:
        """清空所有记录，便于下一次运行从零统计。"""
        with self._lock:
            self._durations.clear()
            self._exec_counts.clear()
            self._step_sequence = 0

    def start_step(self, name: str) -> int:
        """为即将执行的节点分配一个实时步骤号。"""
        del name  # 当前只需要全局步骤号，保留参数便于未来按节点扩展。
        with self._lock:
            self._step_sequence += 1
            return self._step_sequence

    def record(self, name: str, start: float, end: float) -> None:
        """记录一次节点执行：耗时 = end - start，并累加步骤数。

        这也是 E-04"步骤数"的来源：每次进入这个函数都代表图中跑了一个节点。
        """
        dt = max(0.0, end - start)
        with self._lock:
            self._durations.setdefault(name, []).append(dt)
            self._exec_counts[name] = self._exec_counts.get(name, 0) + 1

    def duration_series(self, name: str) -> list[float]:
        """取某节点的时长序列（用于计算均/P50/P95）。"""
        with self._lock:
            return list(self._durations.get(name, []))

    def execution_count(self, name: str) -> int:
        with self._lock:
            return self._exec_counts.get(name, 0)

    def total_steps(self) -> int:
        """一次运行经过的节点总数（agent + 工具 + 辩论节点）。"""
        with self._lock:
            return sum(self._exec_counts.values())

    def node_names(self) -> list[str]:
        with self._lock:
            return list(self._durations.keys())

    def per_node_summary(self) -> dict[str, dict[str, Any]]:
        """每个节点的 {count/mean/p50/p95/min/max/...} 汇总。"""
        with self._lock:
            return {name: summarize(ts) for name, ts in self._durations.items()}

    def total_time(self) -> float:
        """所有节点耗时之和（用于 D-01 聚合 / 和总耗时对比）。"""
        with self._lock:
            return sum(sum(ts) for ts in self._durations.values())


def wrap_graph_nodes(workflow, timer: NodeTimer, on_complete=None, on_start=None):
    """把 StateGraph 的每个节点包裹计时（就地改写节点 runnable），返回同一 workflow。

    实现要点：
    1. 遍历 workflow.nodes，拿到每个节点原本的 runnable（agent 函数或 ToolNode）。
    2. 直接把 ``spec.runnable`` 替换成一个 RunnableLambda：它先记时间戳，
       然后 ``orig.invoke(state)`` 执行原本节点，最后把耗时写入 timer。
       因为 StateGraph 的节点本身就是 runnable，直接替换 runnable 是最小、
       非侵入的做法：不动节点函数、不动边、不动状态 reducer 语义。
    3. 用一个默认参数 ``o=orig`` 捕获原 runnable，避免闭包循环引用导致所有
       节点都指向同一个对象（这是 Python 闭包经典坑）。
    4. 图编译（compile）时自然就是"带计时的图"，所以调用方无需改任何其它代码。

    ``on_start`` 是可选回调 ``on_start(name, step)``，用于节点开始时打印业务动作；
    ``on_complete`` 是可选回调 ``on_complete(name, elapsed)``，用于节点完成时打印耗时。
    """
    for name, spec in list(workflow.nodes.items()):
        orig = spec.runnable  # 原节点可执行对象（agent 函数 或 ToolNode）

        def _timed(state, o=orig, _name=name):
            step = timer.start_step(_name)
            if on_start is not None:
                on_start(_name, step)
            start = time.perf_counter()
            try:
                return o.invoke(state)
            finally:
                end = time.perf_counter()
                elapsed = end - start
                timer.record(_name, start, end)
                if on_complete is not None:
                    on_complete(_name, elapsed)

        spec.runnable = RunnableLambda(_timed)
    return workflow
