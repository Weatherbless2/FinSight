"""TradingAgents 观测与评测层（非侵入式）。

设计目标：不改动核心图的任何逻辑，只在其外层包裹计时与统计，
从而在不破坏现有 609 项回归的前提下，回答 B-01~B-04 / D-01 / D-02 / E-04
等面试问题，并产出可量化、可复现的真实指标。

三个核心组成：
- metrics.py   ：百分位/均值/中位数 等确定性统计（只用标准库）。
- timer.py     ：节点级计时器 + 无侵入包裹图节点（D-01 节点耗时、E-04 步骤数）。
- runner.py    ：一次/多次真实运行，采集节点耗时、总耗时、LLM/工具调用、步骤数。
"""
from .fixtures import fixture_text, install_fixture_data
from .metrics import mean, median, p50, p95, p99, percentile, summarize
from .runner import InstrumentedRunner
from .timer import NodeTimer, wrap_graph_nodes

__all__ = [
    "percentile", "mean", "median", "p50", "p95", "p99", "summarize",
    "NodeTimer", "wrap_graph_nodes", "InstrumentedRunner",
    "fixture_text", "install_fixture_data",
]
