"""B-01 参数拦截率 / B-02 工具成功率 / B-03 重试(降级) / B-04 超时 —— 确定性测试。

第 1 层（确定性自动化测试）：完全 mock 供应商，不访问网络、不依赖真实 API，
稳定可重复，用于验证边界与统计公式。真实耗时的 D-01/D-02 由第 2 层真实运行给出。

核心要点：
- B-01：非法参数在工具入口就被 ToolInputError 拦截，供应商函数 0 次调用，
        拦截率 = 拦截数 / 非法总数 = 100%。
- B-02：供应商正常返回 / 抛错，统计 成功率 = 成功数 / 总调用数。
- B-03：主供应商限流/失败时，接口按配置链"重试"（降级到备用供应商），
        记录实际被调用的供应商次数。
- B-04：模拟供应商 HTTP 超时，断言接口不卡死、并把超时作为明确异常抛出。
"""
import time
from unittest.mock import Mock

import pytest

from tradingagents.agents.utils import core_stock_tools as stock_module
from tradingagents.agents.utils.tool_validation import ToolInputError
from tradingagents.dataflows import interface
from tradingagents.dataflows.errors import VendorRateLimitError

# ---------------------------------------------------------------------------
# B-01 参数拦截率
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_b01_param_interception_rate_100pct(monkeypatch):
    """所有非法参数在工具边界被拦截，供应商 0 次被调用 -> 拦截率 100%。"""
    vendor = Mock(side_effect=AssertionError("供应商函数绝不能在这里被调用"))
    monkeypatch.setattr(stock_module, "route_to_vendor", vendor)

    # 三类典型非法输入：空代码、路径穿越、起止日期颠倒
    illegal_payloads = [
        {"symbol": "", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        {"symbol": "../../etc", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        {"symbol": "AAPL", "start_date": "2026-02-01", "end_date": "2026-01-01"},
    ]
    intercepted = 0
    for payload in illegal_payloads:
        with pytest.raises(ToolInputError, match=r"^INVALID_INPUT:"):
            stock_module.get_stock_data.invoke(payload)
        intercepted += 1

    # 拦截率 = 拦截数 / 非法总数 = 100%
    assert intercepted == len(illegal_payloads)
    vendor.assert_not_called()          # 供应商 0 次调用
    assert intercepted / len(illegal_payloads) == 1.0


# ---------------------------------------------------------------------------
# B-02 工具成功率（用真实的 route_to_vendor，只 mock 供应商实现）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_b02_tool_success_rate(monkeypatch):
    """5 次调用：3 次成功、2 次供应商抛错（核心类别会 raise）-> 成功率 60%。"""
    outcomes = ["ok", "ok", "ok", "err", "err"]
    idx = {"i": 0}

    def fake_vendor(symbol, start_date, end_date):
        kind = outcomes[idx["i"]]
        idx["i"] += 1
        if kind == "err":
            raise RuntimeError("vendor boom")   # 模拟供应商网络/下游故障
        return "OHLCV_DATA"

    monkeypatch.setitem(interface.VENDOR_METHODS["get_stock_data"], "yfinance", fake_vendor)
    # 强制走单供应商链，避免默认配置干扰
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "yfinance")

    total = len(outcomes)
    success = 0
    errors = 0
    for _ in range(total):
        try:
            stock_module.get_stock_data.invoke(
                {"symbol": "AAPL", "start_date": "2026-01-01", "end_date": "2026-02-01"}
            )
            success += 1
        except Exception:
            errors += 1

    assert success + errors == total
    assert success / total == 0.6           # 成功率 60%
    assert errors > 0                        # 核心类别失败必须"响亮"，不能静默吞掉


# ---------------------------------------------------------------------------
# B-03 重试 / 降级（供应商链）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_b03_vendor_fallback_retry(monkeypatch):
    """主供应商限流 -> 接口按配置链重试（降级到备用），记录实际尝试次数。"""
    calls = {"yfinance": 0, "alpha_vantage": 0}

    def yf(symbol, start_date, end_date):
        calls["yfinance"] += 1
        raise VendorRateLimitError("rate limited")   # 主供应商限流

    def av(symbol, start_date, end_date):
        calls["alpha_vantage"] += 1
        return "OHLCV_DATA"

    monkeypatch.setitem(interface.VENDOR_METHODS["get_stock_data"], "yfinance", yf)
    monkeypatch.setitem(interface.VENDOR_METHODS["get_stock_data"], "alpha_vantage", av)
    monkeypatch.setattr(
        interface, "get_vendor", lambda category, method=None: "yfinance,alpha_vantage"
    )

    result = stock_module.get_stock_data.invoke(
        {"symbol": "AAPL", "start_date": "2026-01-01", "end_date": "2026-02-01"}
    )

    assert result == "OHLCV_DATA"                 # 降级成功
    assert calls["yfinance"] == 1                 # 主供应商被尝试 1 次
    assert calls["alpha_vantage"] == 1            # 备用供应商接管 1 次
    assert calls["yfinance"] + calls["alpha_vantage"] == 2   # 总共 2 次供应商尝试


# ---------------------------------------------------------------------------
# B-04 超时（模拟 HTTP 超时）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_b04_timeout_is_surfaced_not_hung(monkeypatch):
    """模拟供应商超时：接口不卡死，并把超时作为明确异常抛给调用方。"""
    def timeout_vendor(symbol, start_date, end_date):
        time.sleep(0.05)                            # 模拟阻塞后才超时
        raise TimeoutError("connect timeout after 5s")

    monkeypatch.setitem(interface.VENDOR_METHODS["get_stock_data"], "yfinance", timeout_vendor)
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "yfinance")

    start = time.perf_counter()
    with pytest.raises(Exception) as excinfo:
        stock_module.get_stock_data.invoke(
            {"symbol": "AAPL", "start_date": "2026-01-01", "end_date": "2026-02-01"}
        )
    elapsed = time.perf_counter() - start

    # 超时在有限时间内返回明确异常，而不是无限卡死
    assert elapsed < 1.0
    assert isinstance(excinfo.value, TimeoutError) or "timeout" in str(excinfo.value).lower()
