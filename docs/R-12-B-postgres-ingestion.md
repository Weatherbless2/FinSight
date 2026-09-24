# R-12-B：真实 Chunk 入 PostgreSQL

## 面试问题

真实财报 Chunk 如何落库？重复导入、同 ID 内容变化和重复来源如何处理？

## 怎么实现

1. `tradingagents/rag/postgres.py` 读取 R-12-A 生成的 `*.chunks.jsonl`。
2. 每行先用 `FinancialDocumentMetadata` 和 `DocumentChunkMetadata` 校验，确认 Chunk 的 `document_id` 属于父文档。
3. `build_import_batch()` 按 `document_id/source_hash/chunk_id` 去重并拦截批次内冲突。
4. `PostgresChunkRepository.import_batch()` 开启事务，先记录 `ingestion_runs=running`，再检查数据库已有文档和 Chunk。
5. 已有记录只有在所有业务字段和正文完全一致时才跳过；来源哈希归属其他文档、文档元数据变化或 Chunk 正文变化都会失败。
6. 新 Chunk 只写正文和位置字段，`content_tsv` 由 PostgreSQL 生成，`embedding` 留空给 R-12-C 写入。
7. 成功更新 `ingestion_runs=succeeded`；失败回滚业务写入，并单独记录 `failed` 和错误信息。

## 运行命令

先只校验真实输入，不需要 Docker：

```bash
cd /root/projects/TradingAgents
.venv/bin/python scripts/load_chunks_to_postgres.py \
  --input-dir data/processed_documents --dry-run
```

Docker 和迁移可用后：

```bash
docker compose --profile rag up -d postgres
docker compose --profile rag exec -T postgres \
  psql -U tradingagents -d tradingagents \
  < db/migrations/001_rag_documents.sql

.venv/bin/pip install -e '.[postgres]'
.venv/bin/python scripts/load_chunks_to_postgres.py \
  --input-dir data/processed_documents
```

如果宿主机的 `5432` 已被其他 PostgreSQL 占用，可将 Docker 映射到 `55432`，然后把连接串改为：

```text
postgresql+psycopg://tradingagents:tradingagents_dev_only@127.0.0.1:55432/tradingagents
```

本次真实验收就是使用这个端口；WSL 中的 `docker` 命令已指向 Docker Desktop 自带的 CLI。

## 实际输出

第一次真实导入：

```text
documents_seen=3
documents_inserted=3
chunks_seen=330
chunks_inserted=330
```

第二次真实导入：

```text
documents_inserted=0
documents_skipped=3
chunks_inserted=0
chunks_skipped=330
```

## 当前实测

- Docker Desktop 已恢复，使用 `pgvector/pgvector:pg16` 启动容器；因本机 `5432` 已被其他 PostgreSQL 占用，本次映射为 `127.0.0.1:55432`。
- 迁移已真实执行，`vector` 和 `pgcrypto` 扩展均存在。
- 数据库查询结果：`documents=3`、`document_chunks=330`、`content_tsv=330`、`embedding=0`。
- `ingestion_runs` 最新记录为 `succeeded`，`documents_seen=3`、`documents_inserted=3`、`error_count=0`。
- 全文检索冒烟查询已命中 AAPL 的 `revenue` Chunk；迁移生成的索引共 10 个，包含 GIN 全文索引和 HNSW 向量索引。
- 当前仍未生成真实 Embedding；`embedding=0` 是 R-12-C 的待办，不是入库失败。

## 取舍与下一步

本工单采用 SQLAlchemy Core，不把数据库连接塞进 Agent 节点；这样导入、检索和 Agent 工作流保持解耦。R-12-C 再选择真实 Embedding Provider，并只更新 `document_chunks.embedding`。Docker Desktop 的 WSL 原生命令入口仍未自动注入，因此本次用 Windows Docker CLI 访问同一 Docker Desktop 后端；这不影响数据库真实验收。

## 30 秒面试答案

我把 RAG 入库做成独立的 SQLAlchemy 仓储。数据先经过 Pydantic 和批次级关系校验，再在事务中写入文档、Chunk 和导入运行记录。重复导入只有在正文和元数据完全一致时才幂等跳过；同一来源哈希换了文档、同一 Chunk ID 内容变化都会失败，避免金融证据被静默覆盖。全文索引由 PostgreSQL 生成，向量写入留给后续 Embedding 工单。
