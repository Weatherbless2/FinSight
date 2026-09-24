# R-03：建立 RAG 文档、片段和导入记录表

## 问题

RAG 的文档、Chunk、向量和导入过程如何持久化，并且如何让重复文档、未来文档和孤立片段在数据库层被拦截？

## 做了什么

- 新增 db/migrations/001_rag_documents.sql。
- 创建 documents 表，保存股票、文档类型、来源、哈希、发布时间和公开时间。
- 创建 document_chunks 表，保存章节、页码、字符区间、正文、全文检索字段和 1536 维向量。
- 创建 ingestion_runs 表，记录导入过程状态和错误数量。
- 增加股票+日期、文档类型、文档片段顺序、全文检索和向量检索索引。
- 增加来源哈希唯一约束、公开日期边界、文档删除级联和片段位置约束。
- 增加两条静态 SQL 冒烟测试，不依赖 Docker。

## 目的

PostgreSQL 负责长期保存 RAG 事实数据，pgvector 负责向量检索，PostgreSQL 全文索引负责关键词检索。数据库约束与 Python 元数据模型形成双重保护，后续导入器即使出现边界 bug，也不能轻易写入未来文档或重复来源。

## VS Code WSL 项目修改

- db/migrations/001_rag_documents.sql：数据库扩展、表、约束和索引。
- tests/test_rag_schema_migration.py：检查迁移文件的核心结构和金融安全约束。
- docs/R-03-rag-schema-migration.md：记录设计、命令和当前限制。

## 应用迁移命令

Docker 可用后，在 VS Code WSL 终端执行：

    cd /root/projects/TradingAgents
    docker compose --profile rag up -d postgres
    docker compose --profile rag exec -T postgres +      psql -U tradingagents -d tradingagents +      < db/migrations/001_rag_documents.sql

查看表和索引：

    docker compose --profile rag exec postgres +      psql -U tradingagents -d tradingagents +      -c "dt; di; dx"

## 测试与结果

    pytest -q tests/test_rag_schema_migration.py

当前只能完成 SQL 文件静态校验；Docker 不可用时不能声称数据库迁移已执行成功。

## 设计取舍

初始向量维度固定为 1536，便于建立 HNSW 索引；R-07 选择 Embedding Provider 时必须匹配该维度，若更换模型需要新增迁移。没有加入 Redis，也没有把数据库连接代码提前放进 Agent。

## 30 秒面试答案

我把文档元数据、片段正文、全文索引和向量索引统一放进 PostgreSQL。数据库层额外增加来源哈希唯一约束、available_at 与 published_at 的日期约束、片段位置约束和级联删除，保证 RAG 数据可追溯且不会产生明显的未来数据或孤立 Chunk。当前先用 SQL 迁移固定结构，再由后续导入器写入数据。

## 当前结果与下一步

迁移文件和静态校验已完成；数据库实际执行仍等待 Docker 环境。下一步是 R-04：导入少量公开 SEC/公司 IR 文档，并记录原文哈希和导入状态。
