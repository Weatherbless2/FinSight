"""确定性统计工具：百分位、均值、中位数（只用标准库，无第三方依赖）。

面试题：如何衡量一次智能体运行的成本 / 延迟？（D-02）
回答：对多次运行采集同一指标（节点耗时、总耗时、步骤数、工具调用数），
用"均值 / P50 / P95"描述其分布。P95 表示 95% 的运行在此时间之内完成，
代表长尾；服务化（F 阶段）最关心的是长尾，而不是平均值。

注意：这里全部只用 Python 标准库，避免引入 numpy，便于单元测试与 CI。
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def percentile(values: Sequence[float], p: float) -> float:
    """线性插值百分位；p 取值 0~100。空序列返回 0.0。

    实现参考 numpy.percentile 的"linear"插值方式：
        排序后位置 rank = p/100 * (n-1)，在 rank 相邻两个样本之间线性插值。
    """
    if not values:
        return 0.0
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    rank = (p / 100.0) * (len(xs) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs[lo]
    frac = rank - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


def mean(values: Sequence[float]) -> float:
    """算术平均。空序列返回 0.0。"""
    return sum(values) / len(values) if values else 0.0


def median(values: Sequence[float]) -> float:
    """中位数 = P50。"""
    return percentile(values, 50)


def p50(values: Sequence[float]) -> float:
    return percentile(values, 50)


def p95(values: Sequence[float]) -> float:
    return percentile(values, 95)


def p99(values: Sequence[float]) -> float:
    return percentile(values, 99)


def summarize(values: Sequence[float]) -> dict[str, Any]:
    """返回一份指标摘要：count/mean/median/p50/p95/p99/min/max。

    这就是面试里说的"量化结果"：不是一句"挺快"，而是
    给出样本量、均值、P50、P95，让结论可被复核。
    """
    xs = [float(v) for v in values]
    return {
        "count": len(xs),
        "mean": round(mean(xs), 4),
        "median": round(median(xs), 4),
        "p50": round(p50(xs), 4),
        "p95": round(p95(xs), 4),
        "p99": round(p99(xs), 4),
        "min": round(min(xs), 4) if xs else None,
        "max": round(max(xs), 4) if xs else None,
    }
