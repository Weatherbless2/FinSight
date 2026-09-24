# R-01：财报与公告文档元数据契约

## 问题

财报、公告和业绩材料进入 RAG 前，如何保证每个文档和片段都能按股票、日期、来源和原文位置追溯？

## 做了什么

- 新增 tradingagents.rag.documents.FinancialDocumentMetadata，定义文档级元数据。
- 新增 tradingagents.rag.documents.DocumentChunkMetadata，定义片段位置元数据。
- 复用项目已有 safe_ticker_component() 校验股票代码。
- 校验来源必须是绝对 HTTP(S) 地址，来源哈希必须是 SHA-256，公开日期不能早于发布时间。
- 增加历史日期判断方法 is_available_at()。
- 增加 3 个最小冒烟测试。

## 目的

后续 PostgreSQL 表、文档解析器、Chunk 切分器和 Hybrid Retrieval 必须使用同一份字段契约。尤其是 available_at 用于防止历史分析检索到未来文档，source_url/source_hash 用于引用和去重，片段页码与字符区间用于回溯原文。

## VS Code WSL 项目修改

- tradingagents/rag/__init__.py：导出两个文档契约模型。
- tradingagents/rag/documents.py：实现字段、来源、股票、日期和位置校验；关键校验函数旁有中文注释。
- tests/test_rag_document_metadata.py：验证正常数据、未来日期边界和非法元数据。
- docs/R-01-document-metadata-contract.md：记录工单设计与面试答案。

核心数据流：

    原始财报/公告
      -> FinancialDocumentMetadata
      -> DocumentChunkMetadata
      -> 后续 PostgreSQL documents/document_chunks 表

## 测试与结果

    pytest -q tests/test_rag_document_metadata.py

本工单只验证契约，不下载文档、不连接 PostgreSQL、不调用 Embedding API。

## 设计取舍

本次没有把正文、向量和数据库连接写进模型，避免 R-01 与后续 R-02/R-05/R-07 耦合。available_at 和 published_at 暂时按日期保存，时区和发布时间精确到时间戳留给真实数据导入工单处理。

## 30 秒面试答案

我先定义了文档和片段的统一元数据契约，而不是直接把文本扔进向量库。文档必须有股票、类型、来源、哈希和公开日期；片段必须记录章节、页码和字符区间。检索前可以用 available_at <= trade_date 做确定性过滤，保证历史分析不会使用未来文档，后续数据库和检索器都复用这份契约。

## 限制与下一步

当前没有真实财报文件、解析器、数据库表或向量。下一步是 R-02：部署 PostgreSQL + pgvector，只完成数据库容器、扩展和连接健康检查。
