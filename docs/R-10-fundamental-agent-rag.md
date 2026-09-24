# R-10：基本面 Agent 接入 API/RAG 路由

## 问题

基本面 Agent 什么时候应该查结构化财务 API，什么时候应该查财报和公告 RAG？如果其中一路失败，如何让 ToolNode 和上层 Agent 看到一致的结果？

## 做了什么

- 新增 `FinancialSearchService`，按查询意图把问题分为 API、RAG 或 API+RAG。
- 数值类问题（营收、EPS、利润、现金流等）优先走现有 `get_fundamentals` API。
- 风险、原因、展望、管理层表态等定性问题走注入的 RAG 搜索服务。
- 混合问题先调用 API，再调用 RAG；一路失败时返回 `PARTIAL_SUCCESS` 和错误信息。
- 新增 `FinancialSearchResult`，统一返回 `success/data/error_code/retryable/source/timestamp`。
- 新增 `search_financial_documents` LangChain 工具并加入基本面 ToolNode；未注入 RAG 时明确返回 `RAG_NOT_CONFIGURED`。
- 修改基本面分析师提示词，让它知道定性问题优先使用文档搜索工具。
- `TradingAgentsGraph` 默认注入原有综合基本面 API，仍可通过构造参数传入 RAG 服务。

## 目的

结构化 API 适合回答“数值是多少”，财报 RAG 适合回答“为什么、风险是什么、管理层怎么说”。把两类能力放在一个工具路由里，Agent 不需要自己猜底层实现；统一结果字段也方便 ToolNode 继续循环、记录失败和后续接入 EvidenceBundle。

## VS Code WSL 项目修改

- `tradingagents/rag/agent_search.py`：路由、统一结果和 LangChain 工具。
- `tradingagents/rag/__init__.py`：导出 R-10 接口。
- `tradingagents/agents/analysts/fundamentals_analyst.py`：接收搜索工具，并把使用条件写进提示词。
- `tradingagents/graph/setup.py`：把搜索工具传入基本面分析师工厂。
- `tradingagents/graph/trading_graph.py`：创建工具节点，默认连接原有基本面 API，支持注入 RAG 服务。
- `tests/test_rag_agent_search.py`：5 个路由、错误和工具 JSON 测试。
- `docs/R-10-fundamental-agent-rag.md`：记录设计和限制。

## 测试与结果

    .venv/bin/pytest -q tests/test_rag_agent_search.py

测试使用 Mock API/RAG，不调用真实模型、文档库或网络；完整 Agent 轨迹和 RAG 质量评测后置到 R-11/R-12。

## 设计取舍

RAG 服务采用构造参数注入，避免在工具模块里写全局数据库连接。默认没有 RAG 时明确失败，不返回伪造的空证据；API 路径继续复用已有工具，保证老工作流兼容。意图识别目前是可解释的关键词规则，后续可以在 R-11 用受约束的 Agentic Retrieval 扩展，但仍要保留轮数和调用上限。

## 30 秒面试答案

我把基本面查询抽象成统一搜索工具：营收、EPS、现金流等精确数值优先走结构化 API；风险、原因、展望和管理层表态走带引用的 RAG；混合问题两路都查。工具统一返回成功状态、数据、错误码、是否可重试、来源和时间戳，避免 Agent 直接处理多个供应商的不同返回格式。

## 当前限制与下一步

当前真正的 RAG 服务仍需要外部注入，默认运行只证明 API 路径和“未配置 RAG”的安全错误；还没有把 `EvidenceBundle` 接到真实 PostgreSQL，也没有加入基本面 Agent 的完整图运行评测。下一步是 R-11：为检索增加查询去重、轮数/工具次数/上下文预算和证据不足停止规则。
