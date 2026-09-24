"""R-10 基本面 Agent API/RAG 路由的最小测试。"""

import json
from datetime import date
from unittest.mock import Mock

from tradingagents.rag.agent_search import (
    FinancialSearchService,
    create_search_financial_documents_tool,
)


def test_numeric_question_prefers_structured_api():
    """数值问题走现有基本面 API，不额外调用 RAG。"""
    api_search = Mock(return_value={"revenue": 100})
    rag_search = Mock(return_value={"citations": []})
    service = FinancialSearchService(api_search=api_search, rag_search=rag_search)

    result = service.search(
        query="What is the revenue and EPS?",
        ticker="aapl",
        curr_date="2025-01-31",
    )

    assert result.success is True
    assert result.source == "api"
    assert result.data == {"api": {"revenue": 100}}
    api_search.assert_called_once_with("AAPL", "2025-01-31")
    rag_search.assert_not_called()


def test_qualitative_question_uses_rag_and_returns_uniform_fields():
    """风险、展望等定性问题走 RAG，并保留统一返回字段。"""
    rag_search = Mock(return_value={"citations": ["chunk-1"]})
    service = FinancialSearchService(rag_search=rag_search)

    result = service.search(
        query="What are the main risks and management outlook?",
        ticker="AAPL",
        curr_date="2025-01-31",
    )

    assert result.success is True
    assert result.source == "rag"
    assert result.error_code is None
    assert result.retryable is False
    assert result.data == {"rag": {"citations": ["chunk-1"]}}
    rag_search.assert_called_once_with(
        "What are the main risks and management outlook?",
        "AAPL",
        date(2025, 1, 31),
    )


def test_mixed_question_runs_api_and_rag_and_reports_partial_failure():
    """同时包含数值和定性意图时两路都执行，单路失败转成部分成功。"""
    api_search = Mock(return_value="revenue report")
    rag_search = Mock(side_effect=RuntimeError("retriever unavailable"))
    service = FinancialSearchService(api_search=api_search, rag_search=rag_search)

    result = service.search(
        query="How did revenue change and what is the outlook?",
        ticker="AAPL",
        curr_date="2025-01-31",
    )

    assert result.success is True
    assert result.source == "api+rag"
    assert result.error_code == "PARTIAL_SUCCESS"
    assert result.retryable is True
    assert result.data["api"] == "revenue report"
    assert "rag" in result.data["errors"]


def test_unconfigured_rag_returns_explicit_retryable_error():
    """未配置 RAG 时不能伪装成空结果，要返回明确错误。"""
    result = FinancialSearchService().search(
        query="Explain the risk outlook.",
        ticker="AAPL",
        curr_date="2025-01-31",
    )

    assert result.success is False
    assert result.error_code == "RAG_NOT_CONFIGURED"
    assert result.retryable is True
    assert result.source == "rag"


def test_langchain_tool_returns_json_with_same_contract():
    """ToolNode 需要字符串结果时，JSON 仍保留统一字段。"""
    service = FinancialSearchService(api_search=lambda ticker, curr_date: "api-result")
    tool = create_search_financial_documents_tool(service)

    payload = json.loads(
        tool.invoke(
            {
                "query": "Give the revenue.",
                "ticker": "AAPL",
                "curr_date": "2025-01-31",
            }
        )
    )

    assert payload["success"] is True
    assert payload["source"] == "api"
    assert payload["data"]["api"] == "api-result"


def test_fundamentals_tool_node_contains_search_tool():
    """图接入边界：基本面 ToolNode 必须暴露统一搜索工具。"""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.financial_search_service = FinancialSearchService()
    node = graph._create_tool_nodes()["fundamentals"]

    assert "search_financial_documents" in node.tools_by_name
