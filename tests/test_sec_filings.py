"""R-14-A SEC 财报发现器测试；不访问真实网络。"""

from datetime import date
from unittest.mock import Mock

import pytest

from tradingagents.rag.sec_filings import (
    SEC_SUBMISSIONS_URL,
    SEC_TICKERS_URL,
    SECClient,
    SECDiscoveryError,
)


def make_response(payload):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def make_client():
    session = Mock()
    session.get.side_effect = [
        make_response({"0": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."}}),
        make_response(
            {
                "filings": {
                    "recent": {
                        "form": ["10-K", "10-Q", "8-K", "10-Q", "10-K"],
                        "filingDate": [
                            "2025-01-29",
                            "2025-04-25",
                            "2025-05-02",
                            "2026-04-25",
                            "2024-01-30",
                        ],
                        "reportDate": [
                            "2024-12-31",
                            "2025-03-31",
                            "2025-05-01",
                            "2026-03-31",
                            "2023-12-31",
                        ],
                        "accessionNumber": [
                            "0001318605-25-000001",
                            "0001318605-25-000002",
                            "0001318605-25-000003",
                            "0001318605-26-000004",
                            "0001318605-24-000005",
                        ],
                        "primaryDocument": [
                            "tsla-20241231.htm",
                            "tsla-20250331.htm",
                            "tsla-20250501.htm",
                            "tsla-20260331.htm",
                            "tsla-20231231.htm",
                        ],
                        "fy": [2024, 2025, 2025, 2026, 2023],
                        "fp": ["FY", "Q1", "Q1", "Q1", "FY"],
                    }
                }
            }
        ),
    ]
    return SECClient(session=session, user_agent="test@example.com"), session


def test_discover_filters_future_filings_and_builds_archive_urls():
    client, session = make_client()

    filings = client.discover_filings(
        "tsla",
        as_of=date(2025, 3, 1),
        forms=("10-K", "10-Q", "8-K"),
        limit_per_form=None,
    )

    assert [item.form for item in filings] == ["10-K", "10-K"]
    assert filings[0].ticker == "TSLA"
    assert filings[0].document_type == "annual_report"
    assert filings[0].available_at == date(2025, 1, 29)
    assert filings[0].fiscal_period == "FY2024-FY"
    assert filings[0].source_url == (
        "https://www.sec.gov/Archives/edgar/data/1318605/"
        "000131860525000001/tsla-20241231.htm"
    )
    assert session.get.call_args_list[0].args == (SEC_TICKERS_URL,)
    assert session.get.call_args_list[1].args == (SEC_SUBMISSIONS_URL.format(cik=1318605),)
    assert session.get.call_args.kwargs["headers"]["User-Agent"] == "test@example.com"


def test_limit_is_applied_per_form():
    client, _ = make_client()
    filings = client.discover_filings(
        "TSLA", as_of=date(2025, 12, 31), forms=("10-K",), limit_per_form=1
    )
    assert len(filings) == 1


def test_unknown_ticker_is_rejected():
    session = Mock()
    session.get.return_value = make_response({})
    client = SECClient(session=session)

    with pytest.raises(SECDiscoveryError, match="company not found"):
        client.discover_filings("UNKNOWN", as_of=date(2025, 1, 1))


def test_future_date_and_invalid_limit_are_rejected():
    client, _ = make_client()
    with pytest.raises(ValueError, match="limit_per_form"):
        client.discover_filings("TSLA", limit_per_form=0)
