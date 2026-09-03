"""LLM-facing tool contracts reject bad arguments before vendor I/O."""

from __future__ import annotations

from unittest.mock import Mock, call

import pytest

from tradingagents.agents.utils.tool_validation import ToolInputError


@pytest.mark.unit
@pytest.mark.parametrize(
    ("module_name", "tool_name", "payload"),
    [
        (
            "tradingagents.agents.utils.core_stock_tools",
            "get_stock_data",
            {"symbol": "", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        ),
        (
            "tradingagents.agents.utils.core_stock_tools",
            "get_stock_data",
            {"symbol": "../../etc", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        ),
        (
            "tradingagents.agents.utils.core_stock_tools",
            "get_stock_data",
            {"symbol": "AAPL", "start_date": "2026-02-01", "end_date": "2026-01-01"},
        ),
        (
            "tradingagents.agents.utils.news_data_tools",
            "get_news",
            {"ticker": "AAPL", "start_date": "2026-01-32", "end_date": "2026-02-01"},
        ),
        (
            "tradingagents.agents.utils.news_data_tools",
            "get_news",
            {"ticker": "AAPL", "start_date": "2026-02-01", "end_date": "2026-01-01"},
        ),
        (
            "tradingagents.agents.utils.news_data_tools",
            "get_global_news",
            {"curr_date": "2026/02/01"},
        ),
        (
            "tradingagents.agents.utils.news_data_tools",
            "get_global_news",
            {"curr_date": "2026-02-01", "look_back_days": 0},
        ),
        (
            "tradingagents.agents.utils.news_data_tools",
            "get_global_news",
            {"curr_date": "2026-02-01", "limit": 101},
        ),
        (
            "tradingagents.agents.utils.news_data_tools",
            "get_insider_transactions",
            {"ticker": "../AAPL"},
        ),
        (
            "tradingagents.agents.utils.technical_indicators_tools",
            "get_indicators",
            {"symbol": "AAPL", "indicator": "rsi,not_supported", "curr_date": "2026-02-01"},
        ),
        (
            "tradingagents.agents.utils.technical_indicators_tools",
            "get_indicators",
            {"symbol": "AAPL", "indicator": "rsi", "curr_date": "2026-02-01", "look_back_days": 0},
        ),
        (
            "tradingagents.agents.utils.fundamental_data_tools",
            "get_fundamentals",
            {"ticker": "AAPL", "curr_date": "tomorrow"},
        ),
        (
            "tradingagents.agents.utils.fundamental_data_tools",
            "get_balance_sheet",
            {"ticker": "AAPL", "freq": "monthly"},
        ),
        (
            "tradingagents.agents.utils.fundamental_data_tools",
            "get_cashflow",
            {"ticker": "AAPL", "curr_date": "2026-02-30"},
        ),
        (
            "tradingagents.agents.utils.fundamental_data_tools",
            "get_income_statement",
            {"ticker": "AAPL", "freq": "yearly"},
        ),
        (
            "tradingagents.agents.utils.macro_data_tools",
            "get_macro_indicators",
            {"indicator": "   ", "curr_date": "2026-02-01"},
        ),
        (
            "tradingagents.agents.utils.macro_data_tools",
            "get_macro_indicators",
            {"indicator": "cpi", "curr_date": "2026-02-01", "look_back_days": -1},
        ),
        (
            "tradingagents.agents.utils.market_data_validation_tools",
            "get_verified_market_snapshot",
            {"symbol": "AAPL/../../x", "curr_date": "2026-02-01"},
        ),
        (
            "tradingagents.agents.utils.market_data_validation_tools",
            "get_verified_market_snapshot",
            {"symbol": "AAPL", "curr_date": "2026-02-01", "look_back_days": 0},
        ),
        (
            "tradingagents.agents.utils.prediction_markets_tools",
            "get_prediction_markets",
            {"topic": "", "limit": 5},
        ),
        (
            "tradingagents.agents.utils.prediction_markets_tools",
            "get_prediction_markets",
            {"topic": "Fed", "limit": 101},
        ),
    ],
)
def test_invalid_payload_never_reaches_vendor(monkeypatch, module_name, tool_name, payload):
    """Every invalid sample is rejected at the tool boundary (not downstream)."""
    module = __import__(module_name, fromlist=[tool_name])
    if hasattr(module, "route_to_vendor"):
        vendor = Mock(side_effect=AssertionError("vendor must not be called"))
        monkeypatch.setattr(module, "route_to_vendor", vendor)
    else:
        vendor = Mock(side_effect=AssertionError("builder must not be called"))
        monkeypatch.setattr(module, "build_verified_market_snapshot", vendor)

    tool = getattr(module, tool_name)
    with pytest.raises(ToolInputError, match=r"^INVALID_INPUT:") as error:
        tool.invoke(payload)

    assert error.value.code == "INVALID_INPUT"
    vendor.assert_not_called()


@pytest.mark.unit
def test_multiple_indicators_are_normalized_before_each_vendor_call(monkeypatch):
    from tradingagents.agents.utils import technical_indicators_tools as module

    vendor = Mock(side_effect=lambda method, *args: f"{args[1]} ok")
    monkeypatch.setattr(module, "route_to_vendor", vendor)

    result = module.get_indicators.invoke(
        {
            "symbol": " AAPL ",
            "indicator": " RSI, macd ",
            "curr_date": "2026-02-01",
            "look_back_days": 20,
        }
    )

    assert result == "rsi ok\n\nmacd ok"
    assert vendor.call_args_list == [
        call("get_indicators", "AAPL", "rsi", "2026-02-01", 20),
        call("get_indicators", "AAPL", "macd", "2026-02-01", 20),
    ]


@pytest.mark.unit
def test_optional_statement_date_none_is_forwarded(monkeypatch):
    from tradingagents.agents.utils import fundamental_data_tools as module

    vendor = Mock(return_value="ok")
    monkeypatch.setattr(module, "route_to_vendor", vendor)

    assert module.get_balance_sheet.invoke({"ticker": "AAPL"}) == "ok"
    vendor.assert_called_once_with("get_balance_sheet", "AAPL", "quarterly", None)


@pytest.mark.unit
def test_valid_global_news_defaults_are_forwarded(monkeypatch):
    from tradingagents.agents.utils import news_data_tools as module

    vendor = Mock(return_value="ok")
    monkeypatch.setattr(module, "route_to_vendor", vendor)

    assert module.get_global_news.invoke({"curr_date": "2026-02-01"}) == "ok"
    vendor.assert_called_once_with("get_global_news", "2026-02-01", None, None)
