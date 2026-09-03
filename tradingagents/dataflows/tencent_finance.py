"""Keyless Tencent Finance daily bars for Hong Kong listed equities."""

from __future__ import annotations

import re
from io import StringIO

import pandas as pd
import requests

from .errors import NoMarketDataError

_HK_SYMBOL = re.compile(r"^(?P<code>\d{1,5})\.HK$", re.IGNORECASE)
_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_REQUEST_TIMEOUT = 20


def _tencent_hk_symbol(symbol: str) -> str:
    match = _HK_SYMBOL.fullmatch(symbol.strip())
    if not match:
        raise NoMarketDataError(
            symbol,
            symbol,
            "Tencent Finance daily bars are available only for .HK symbols",
        )
    return f"hk{match.group('code').zfill(5)}"


def get_hk_stock(symbol: str, start_date: str, end_date: str) -> str:
    """Return forward-adjusted daily OHLCV CSV for a Hong Kong stock.

    Tencent Finance is used as a keyless fallback for ``.HK`` symbols because
    Yahoo Finance may throttle them and Alpha Vantage's free daily endpoint
    does not cover Hong Kong listings.
    """
    market_symbol = _tencent_hk_symbol(symbol)
    params = {
        "param": f"{market_symbol},day,{start_date},{end_date},320,qfq",
    }
    response = requests.get(_KLINE_URL, params=params, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    bars = payload.get("data", {}).get(market_symbol, {}).get("day", [])
    if not bars:
        raise NoMarketDataError(
            symbol,
            f"{symbol.upper()} (Tencent: {market_symbol})",
            f"no daily rows between {start_date} and {end_date}",
        )

    data = pd.DataFrame(
        [bar[:6] for bar in bars],
        columns=["Date", "Open", "Close", "High", "Low", "Volume"],
    )
    data = data[["Date", "Open", "High", "Low", "Close", "Volume"]]
    for column in ("Open", "High", "Low", "Close", "Volume"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["Date", "Close"])
    if data.empty:
        raise NoMarketDataError(symbol, symbol, "Tencent Finance returned unusable daily rows")

    return data.to_csv(index=False)


def get_hk_stock_dataframe(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Return Tencent Finance daily bars as a normalized DataFrame."""
    return pd.read_csv(StringIO(get_hk_stock(symbol, start_date, end_date)))
