# R-08：Hybrid Retrieval

## 问题

金融问题既可能包含精确词项（如“Revenue”或“风险因素”），也可能是语义表达。如何同时使用关键词和向量检索，并确保股票、日期和文档类型边界不会被模型或排序逻辑绕过？

## 做了什么

- 新增 `IndexedChunk`，把父文档元数据、Chunk 正文和向量绑定，并校验文档 ID 和向量维度。
- 新增 `HybridRetriever`：先过滤 `ticker`、`available_at <= as_of` 和 `document_type`，再计算候选。
- 向量侧取 Top-20，关键词侧取 Top-20；使用 RRF（默认 `rrf_k=60`）融合并返回 Top-K。
- `RetrievalHit` 返回 Chunk、来源 URL、发布时间、公开时间、章节和向量/关键词/融合分数，供后续引用校验使用。
- 关键词基线使用轻量中英文分词和词项覆盖率；后续 PostgreSQL 适配时替换为 `tsvector` 查询，保持返回契约不变。

## 目的

向量检索擅长语义相近表达，关键词检索擅长公司名称、指标名和精确术语。Hybrid Retrieval 可以减少单一路径漏召回，同时把金融日期过滤放在检索前，避免历史分析看到未来公告。

## VS Code WSL 项目修改

- `tradingagents/rag/retrieval.py`：过滤、余弦相似度、关键词基线、RRF 融合和结果契约；日期边界旁有中文注释。
- `tradingagents/rag/__init__.py`：导出 `HybridRetriever`、`IndexedChunk` 和 `RetrievalHit`。
- `tests/test_rag_retrieval.py`：3 个最小测试，覆盖未来文档/跨股票过滤、RRF 双路融合和类型过滤。
- `docs/R-08-hybrid-retrieval.md`：记录算法、命令、取舍和限制。

## 测试与结果

    .venv/bin/pytest -q tests/test_rag_retrieval.py

测试使用固定向量 Provider，不调用真实 Embedding API 或 PostgreSQL；完整 Recall@5、MRR、未来泄露率和 P95 仍集中在 R-12。

## 设计取舍

第一版使用 RRF，不让向量分数和关键词分数直接相加，避免两个分数尺度不同导致某一路径失控；暂不接 Reranker。关键词实现是本地可测试基线，真实数据量上来后由 PostgreSQL `tsvector` 和 pgvector SQL 承担候选召回。

## 30 秒面试答案

我先做确定性过滤，按股票、分析日期和文档类型排除不合法文档，再分别取向量 Top-20 和关键词 Top-20，用 RRF 融合成 Top-10。返回结果不只有文本，还带 Chunk ID、来源 URL、公开日期、章节和各路分数，后续可以做引用校验和离线 Recall 评测。

## 当前限制与下一步

当前检索运行在内存中，关键词是轻量基线，还没有执行 PostgreSQL 的真实 `tsvector`/pgvector 查询；Mock/固定向量也不能证明真实语义召回质量。下一步是 R-09：建立 `EvidenceBundle`，校验引用存在、股票一致、来源合法和日期不晚于分析日。
