# R-11：受约束 Agentic Retrieval

## 问题

如果第一次检索没有证据，Agent 是否可以继续改写查询？怎样防止反复查询、无限循环和上下文不断变大？

## 做了什么

- 新增 `AgenticRetrievalConfig`，默认最多 2 轮、3 次查询、每轮 6 个片段。
- 新增 Query 指纹，忽略大小写和多余空格后用 SHA-256 去重。
- 新增 `ConstrainedRetrievalRunner`，把 R-08 检索函数包装成有限状态运行器。
- 证据不足时可调用注入的 `query_rewriter`；改写为空、超长或重复时停止。
- 每个片段只进入上下文一次；上下文同时受字符数和估算 token 数限制。
- 新增 `RetrievalTrace`，记录轮次、Query、指纹、返回片段数、实际加入数和停止原因。
- 检索异常统一返回 `RETRIEVAL_ERROR` 和 `retryable=True`，不继续盲目循环。

## 目的

RAG Agent 需要一点自主性来改写问题，但金融系统不能允许它无限调用检索工具。R-11 把轮数、调用次数、Query 去重、片段数和上下文预算变成代码限制，模型只能在预算内行动。

## VS Code WSL 项目修改

- `tradingagents/rag/agentic_retrieval.py`：预算配置、查询指纹、有限循环、上下文拼接和 Trace。
- `tradingagents/rag/__init__.py`：导出 R-11 接口。
- `tests/test_rag_agentic_retrieval.py`：4 个测试，覆盖证据命中、一次改写、重复查询停止、上下文超限和检索异常。
- `docs/R-11-constrained-agentic-retrieval.md`：记录设计、命令和限制。

## 测试与结果

    .venv/bin/pytest -q tests/test_rag_agentic_retrieval.py

测试使用固定检索函数，不调用真实 LLM 或 PostgreSQL；R-12 再对关键词、向量、Hybrid 和 Agentic 四种方法做完整指标对比。

## 设计取舍

查询改写通过依赖注入，不在本工单直接调用 LLM，保证测试确定性；没有改写器时证据不足就停止。默认预算偏保守，先保证不会死循环，后续根据 R-12 的 Recall、P95 和 Token 数据调整。

## 30 秒面试答案

我没有让 Agent 无限自主检索，而是用运行器限制最多 2 轮、3 次查询、每轮 6 个片段，并用 Query 指纹去重。每个片段只加入上下文一次，同时限制字符和估算 Token；如果没有证据，改写为空或重复就停止，并记录停止原因和完整轨迹。

## 当前限制与下一步

当前运行器还没有接入基本面 Agent 的真实工具调用轨迹，Query 改写器也只是可注入接口；上下文 Token 使用确定性估算，不代表具体模型 tokenizer。下一步是 R-12：用固定评测集比较四种检索方案的 Recall@5、MRR、引用覆盖率、未来泄露率、P95 和 Token。
