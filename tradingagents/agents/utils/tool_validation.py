"""Pydantic validation shared by LLM-facing data tools."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from tradingagents.dataflows.utils import safe_ticker_component

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INDICATORS = frozenset(
    {
        "close_50_sma",
        "close_200_sma",
        "close_10_ema",
        "macd",
        "macds",
        "macdh",
        "rsi",
        "boll",
        "boll_ub",
        "boll_lb",
        "atr",
        "vwma",
    }
)


class ToolInputError(ValueError):
    """Stable error for invalid model/tool arguments."""

    code = "INVALID_INPUT"

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        suffix = f" (field={field})" if field else ""
        super().__init__(f"{self.code}: {message}{suffix}")


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validate_ticker(value: str) -> str:
    try:
        return safe_ticker_component(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def _validate_date(value: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError("must use YYYY-MM-DD format")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("is not a valid calendar date") from exc
    return value


def _validate_optional_date(value: str | None) -> str | None:
    """Validate a nullable date without rejecting an omitted tool argument."""
    if value is None:
        return None
    return _validate_date(value)


class StockDataInput(_ToolInput):
    symbol: str = Field(min_length=1, max_length=32)
    start_date: str
    end_date: str

    _ticker = field_validator("symbol")(_validate_ticker)
    _dates = field_validator("start_date", "end_date")(_validate_date)

    @model_validator(mode="after")
    def check_date_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class NewsInput(_ToolInput):
    ticker: str = Field(min_length=1, max_length=32)
    start_date: str
    end_date: str

    _ticker = field_validator("ticker")(_validate_ticker)
    _dates = field_validator("start_date", "end_date")(_validate_date)

    @model_validator(mode="after")
    def check_date_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class IndicatorInput(_ToolInput):
    symbol: str = Field(min_length=1, max_length=32)
    indicator: str = Field(min_length=1, max_length=256)
    curr_date: str
    look_back_days: int = Field(default=30, ge=1, le=3650)

    _ticker = field_validator("symbol")(_validate_ticker)
    _date = field_validator("curr_date")(_validate_date)

    @field_validator("indicator")
    @classmethod
    def check_indicators(cls, value: str) -> str:
        names = [item.strip().lower() for item in value.split(",") if item.strip()]
        invalid = sorted(set(names) - _INDICATORS)
        if not names:
            raise ValueError("must contain at least one indicator")
        if invalid:
            raise ValueError(
                f"unsupported indicator(s): {', '.join(invalid)}"
            )
        return ",".join(names)


class DateWindowInput(_ToolInput):
    curr_date: str
    look_back_days: int | None = Field(default=None, ge=1, le=3650)

    _date = field_validator("curr_date")(_validate_date)


class PredictionMarketsInput(_ToolInput):
    topic: str = Field(min_length=1, max_length=200)
    limit: int | None = Field(default=None, ge=1, le=100)


class FundamentalInput(_ToolInput):
    ticker: str = Field(min_length=1, max_length=32)
    curr_date: str

    _ticker = field_validator("ticker")(_validate_ticker)
    _date = field_validator("curr_date")(_validate_date)


class FundamentalStatementInput(_ToolInput):
    ticker: str = Field(min_length=1, max_length=32)
    freq: Literal["annual", "quarterly"] = "quarterly"
    curr_date: str | None = None

    _ticker = field_validator("ticker")(_validate_ticker)
    _date = field_validator("curr_date")(_validate_optional_date)


class InsiderInput(_ToolInput):
    ticker: str = Field(min_length=1, max_length=32)

    _ticker = field_validator("ticker")(_validate_ticker)


class VerifiedSnapshotInput(_ToolInput):
    symbol: str = Field(min_length=1, max_length=32)
    curr_date: str
    look_back_days: int = Field(default=30, ge=1, le=3650)

    _ticker = field_validator("symbol")(_validate_ticker)
    _date = field_validator("curr_date")(_validate_date)


class GlobalNewsInput(_ToolInput):
    """Input contract for the optional global-news enrichment tool."""

    curr_date: str
    look_back_days: int | None = Field(default=None, ge=1, le=3650)
    limit: int | None = Field(default=None, ge=1, le=100)

    _date = field_validator("curr_date")(_validate_date)


class MacroInput(_ToolInput):
    """Input contract for a FRED macroeconomic series request."""

    indicator: str = Field(min_length=1, max_length=64)
    curr_date: str
    look_back_days: int | None = Field(default=None, ge=1, le=3650)

    _date = field_validator("curr_date")(_validate_date)

    @field_validator("indicator")
    @classmethod
    def check_indicator(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain a macro indicator or FRED series ID")
        return value


ModelT = TypeVar("ModelT", bound=_ToolInput)


def validate_tool_input(model: type[ModelT], **values: Any) -> ModelT:
    """Validate a tool payload and expose one stable application error."""
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or None
        raise ToolInputError(first["msg"], field=location) from exc
