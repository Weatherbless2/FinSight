# R-09：引用与日期校验

## 问题

检索结果交给基本面 Agent 前，如何确认引用的 Chunk 真实存在、属于当前股票、来源合法，并且在历史分析日已经公开？

## 做了什么

- 新增 `EvidenceCitation`，统一保存 `chunk_id`、`document_id`、股票、来源 URL、公开日期、章节和正文摘录。
- 新增 `EvidenceBundle`，保存查询、股票、分析日期和去重后的引用集合。
- 新增 `build_evidence_bundle()`，逐字段对照 `RetrievalHit` 与索引中的真实 `IndexedChunk`。
- 拒绝不存在的 Chunk、跨股票引用、来源不一致、日期不一致、未来文档和被篡改的正文。
- 对直接构造的 `EvidenceBundle` 也再次检查股票一致性、引用唯一性和 `available_at <= as_of`。

## 目的

RAG 的回答不能只给一段相似文本，还要能定位到原始文档。金融场景尤其需要防止历史回测看到未来公告，以及模型把 AAPL 的证据标成 MSFT。R-09 把这些规则放在确定性代码中，不交给模型判断。

## VS Code WSL 项目修改

- `tradingagents/rag/evidence.py`：证据模型、索引对照和日期/来源校验；关键安全边界有中文注释。
- `tradingagents/rag/__init__.py`：导出证据包相关接口。
- `tests/test_rag_evidence.py`：3 个最小测试，覆盖正常引用、未来/跨股票拒绝、缺失 Chunk 和篡改正文拒绝。
- `docs/R-09-evidence-validation.md`：记录设计、命令、取舍和限制。

## 测试与结果

    .venv/bin/pytest -q tests/test_rag_evidence.py

本工单只验证引用契约和金融日期边界，不调用真实 LLM、不连接 PostgreSQL，也不宣称回答质量提升。完整引用覆盖率和未来泄露率在 R-12 统一统计。

## 设计取舍

证据包只接受已经通过 R-08 检索的 `RetrievalHit`，并要求它和索引原文逐字段一致，避免调用方自行拼接来源。当前 `text_excerpt` 直接保存完整 Chunk，后续可按报告上下文预算做截断，但必须保留 Chunk ID 和来源。

## 30 秒面试答案

我没有直接把检索文本交给模型，而是先构造 `EvidenceBundle`。代码会校验 Chunk 存在、股票和文档一致、来源 URL 一致、正文没有被篡改，并强制 `available_at <= as_of`。这样模型只能基于可追溯且不泄露未来信息的证据生成报告。

## 当前限制与下一步

当前证据校验运行在内存索引上，尚未接入真实 PostgreSQL 查询结果，也没有做报告级引用覆盖率统计。下一步是 R-10：为基本面 Agent 增加 `search_financial_documents()`，让它根据问题在结构化 API、RAG 或两者之间选择，并统一返回错误和来源字段。
