from typing import Annotated

from langchain_core.tools import tool

from tradingagents.agents.utils.tool_validation import (
    GlobalNewsInput,
    InsiderInput,
    NewsInput,
    validate_tool_input,
)
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    payload = validate_tool_input(
        NewsInput,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
    )
    return route_to_vendor(
        "get_news", payload.ticker, payload.start_date, payload.end_date
    )

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    payload = validate_tool_input(
        GlobalNewsInput,
        curr_date=curr_date,
        look_back_days=look_back_days,
        limit=limit,
    )
    return route_to_vendor(
        "get_global_news", payload.curr_date, payload.look_back_days, payload.limit
    )

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    payload = validate_tool_input(InsiderInput, ticker=ticker)
    return route_to_vendor("get_insider_transactions", payload.ticker)
