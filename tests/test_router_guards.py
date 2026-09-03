"""Regression tests for bounded and diagnosable graph routing."""

from types import SimpleNamespace

import pytest

from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator


@pytest.mark.unit
@pytest.mark.parametrize(
    "router_name",
    [
        "should_continue_market",
        "should_continue_social",
        "should_continue_news",
        "should_continue_fundamentals",
    ],
)
def test_analyst_router_rejects_empty_messages(router_name):
    logic = ConditionalLogic()

    with pytest.raises(ValueError, match="messages cannot be empty"):
        getattr(logic, router_name)({"messages": []})


@pytest.mark.unit
def test_propagator_sets_explicit_recursion_limit():
    args = Propagator(max_recur_limit=7).get_graph_args()

    assert args["config"]["recursion_limit"] == 7


@pytest.mark.unit
def test_debate_router_stops_at_exact_round_limit():
    logic = ConditionalLogic(max_debate_rounds=2)
    state = {
        "investment_debate_state": {
            "count": 4,
            "current_response": "Bull Researcher: continue",
        }
    }

    assert logic.should_continue_debate(state) == "Research Manager"


@pytest.mark.unit
def test_risk_router_stops_at_exact_round_limit():
    logic = ConditionalLogic(max_risk_discuss_rounds=2)
    state = {
        "risk_debate_state": {
            "count": 6,
            "latest_speaker": "Aggressive Analyst",
        }
    }

    assert logic.should_continue_risk_analysis(state) == "Portfolio Manager"


@pytest.mark.unit
def test_analyst_router_returns_only_declared_targets():
    logic = ConditionalLogic()
    finished = {"messages": [SimpleNamespace(tool_calls=[])]}
    tool_call = {"messages": [SimpleNamespace(tool_calls=[{"name": "snapshot"}])]}

    assert logic.should_continue_market(finished) == "Msg Clear Market"
    assert logic.should_continue_market(tool_call) == "tools_market"
