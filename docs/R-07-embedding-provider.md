# R-07：Embedding Provider 与向量契约

## 问题

Chunk 已经切好后，如何把正文稳定转换成向量，并保证模型输出可以写入 PostgreSQL 的 `VECTOR(1536)`？供应商调用失败时，如何知道哪些片段需要重试？

## 做了什么

- 新增 `EmbeddingModelConfig`，统一保存 provider、模型名、模型版本和向量维度。
- 新增 `EmbeddingProvider` 抽象，真实供应商后续只需要实现 `embed()`。
- 新增 `MockEmbeddingProvider`，使用 SHA-256 生成确定性、归一化的 1536 维向量，不调用网络。
- 新增 `ChunkEmbedding` 结果对象，保存 Chunk ID、模型版本、状态、向量、错误和 `retryable` 标记。
- 对供应商输出做维度、有限浮点数和全零向量校验；单个 Chunk 失败会形成可重试失败记录。
- 在 `tradingagents.rag` 中导出上述接口，供后续向量入库和检索工单复用。

## 目的

R-03 已把数据库向量列固定为 `VECTOR(1536)`。本工单先把模型契约和失败语义固定下来，避免真实 Embedding API 接入后出现维度不匹配、NaN 或失败片段静默丢失。Mock 让本地测试不依赖密钥、网络和 PostgreSQL。

## VS Code WSL 项目修改

- `tradingagents/rag/embeddings.py`：Embedding 配置、Provider 抽象、向量校验、Mock Provider 和失败状态；关键边界有中文注释。
- `tradingagents/rag/__init__.py`：导出 R-07 公共接口。
- `tests/test_rag_embeddings.py`：3 个最小测试，覆盖确定性向量、维度边界和失败重试状态。
- `docs/R-07-embedding-provider.md`：记录工单设计、命令、取舍和限制。

## 测试与结果

在 WSL 项目目录执行：

    .venv/bin/pytest -q tests/test_rag_embeddings.py

本工单的测试只验证本地 Mock 和契约，不声称真实 Embedding 模型质量，也不连接 PostgreSQL。完整 Recall@K、MRR、P95 和 Token 评测统一放在 R-12。

## 设计取舍

当前严格绑定 `VECTOR(1536)`，更换维度必须新增数据库迁移，而不是运行时悄悄截断向量。Mock 使用哈希生成确定性向量，优点是零外部依赖，缺点是没有真实语义能力；真实模型和批量 API 重试留给后续接入工单。

## 30 秒面试答案

我先把 Embedding 做成 Provider 抽象，配置中固定模型版本和 1536 维度，并在写入前校验维度、NaN 和全零向量。开发阶段用确定性的 Mock，不依赖外部 API；单个 Chunk 失败会保留模型版本、错误原因和可重试状态，后续可以安全接入真实供应商和 PostgreSQL。

## 当前限制与下一步

当前没有接入真实 Embedding API，也没有把向量写入 PostgreSQL；Mock 不能证明语义召回质量。下一步是 R-08：先按 `ticker`、`available_at` 和文档类型做过滤，再实现向量 Top-K 与 PostgreSQL 全文 Top-K 的 Hybrid Retrieval。
