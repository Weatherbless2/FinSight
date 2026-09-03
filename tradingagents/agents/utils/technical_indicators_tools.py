from typing import Annotated

from langchain_core.tools import tool

from tradingagents.agents.utils.tool_validation import IndicatorInput, validate_tool_input
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    """
    Retrieve a single technical indicator for a given ticker symbol.
    Uses the configured technical_indicators vendor.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        indicator (str): A single technical indicator name, e.g. 'rsi', 'macd'. Call this tool once per indicator.
        curr_date (str): The current trading date you are trading on, YYYY-mm-dd
        look_back_days (int): How many days to look back, default is 30
    Returns:
        str: A formatted dataframe containing the technical indicators for the specified ticker symbol and indicator.
    """
    payload = validate_tool_input(
        IndicatorInput,
        symbol=symbol,
        indicator=indicator,
        curr_date=curr_date,
        look_back_days=look_back_days,
    )
    # LLMs sometimes pass multiple indicators as a comma-separated string;
    # validation normalizes and checks every name before any vendor call.
    indicators = payload.indicator.split(",")
    results = []
    for ind in indicators:
        try:
            results.append(
                route_to_vendor(
                    "get_indicators",
                    payload.symbol,
                    ind,
                    payload.curr_date,
                    payload.look_back_days,
                )
            )
        except ValueError as e:
            results.append(str(e))
    return "\n\n".join(results)
