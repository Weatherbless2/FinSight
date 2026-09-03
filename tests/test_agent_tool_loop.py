"""Deterministic regression test for the analyst tool-calling loop."""

from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict


class LoopState(TypedDict):
    messages: Annotated[list, add_messages]
    report: str


@tool
def get_stock_snapshot(ticker: str) -> str:
    """Return a deterministic market snapshot used by the test."""
    return f"{ticker.upper()}：价格 100，涨跌 +1.5%"


class FakeModel:
    """Return one tool call, then a final report without network access."""

    def __init__(self) -> None:
        self.call_count = 0
        self.received_messages = []

    def invoke(self, messages):
        self.call_count += 1
        self.received_messages.append(messages)
        if self.call_count == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_stock_snapshot",
                        "args": {"ticker": "NVDA"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="最终报告：NVDA 当前走势偏强。")


def test_agent_tool_loop_returns_to_agent_and_writes_report():
    fake_model = FakeModel()
    tool_node = ToolNode([get_stock_snapshot])
    visited_nodes: list[str] = []

    def agent_node(state: LoopState):
        visited_nodes.append("agent")
        response = fake_model.invoke(state["messages"])
        update = {"messages": [response]}
        if not response.tool_calls:
            update["report"] = response.content
        return update

    def tools_node(state: LoopState):
        visited_nodes.append("tools")
        return tool_node.invoke(state)

    def route_after_agent(state: LoopState):
        return "tools" if state["messages"][-1].tool_calls else END

    graph = StateGraph(LoopState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    result = graph.compile().invoke(
        {"messages": [HumanMessage(content="分析 NVDA")], "report": ""}
    )

    assert visited_nodes == ["agent", "tools", "agent"]
    assert fake_model.call_count == 2
    assert "NVDA：价格 100" in fake_model.received_messages[1][-1].content
    assert "最终报告" in result["report"]
    assert len(result["messages"]) == 4
