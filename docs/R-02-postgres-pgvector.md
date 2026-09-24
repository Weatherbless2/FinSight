# R-02：部署 PostgreSQL + pgvector

## 问题

RAG 的文档、元数据、片段和向量应该放在哪里？如何保证数据库服务可启动、数据可持久化，并且不会影响当前默认的本地 Agent 流程？

## 做了什么

- 在 docker-compose.yml 增加 PostgreSQL 16 + pgvector 服务。
- 将数据库放在 rag profile 下，默认启动现有 TradingAgents 服务时不会自动拉起数据库。
- 增加数据库名、用户、密码和端口的环境变量模板。
- 增加 PostgreSQL 数据卷，容器重建后保留数据。
- 增加 pg_isready 健康检查，只检查连接状态，不执行写入。

## 目的

PostgreSQL 后续保存财报、公告、文档片段和索引元数据，pgvector 后续保存 Embedding。现在只建立基础设施，不建业务表、不下载文档、不连接 Agent，避免数据库基础设施和 RAG 业务逻辑耦合。

## VS Code WSL 项目修改

- docker-compose.yml：新增 postgres 服务、rag profile、健康检查和 tradingagents_postgres_data 数据卷。
- .env.example：新增 POSTGRES_DB、POSTGRES_USER、POSTGRES_PASSWORD、POSTGRES_PORT 模板。
- docs/R-02-postgres-pgvector.md：记录启动命令、验收方式和当前限制。

## 运行命令

在 VS Code 的 WSL 终端中执行：

    cd /root/projects/TradingAgents
    docker compose --profile rag up -d postgres
    docker compose --profile rag ps postgres

检查 pgvector：

    docker compose --profile rag exec postgres psql -U tradingagents -d tradingagents -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extversion FROM pg_extension WHERE extname = 'vector';"

停止服务但保留数据库数据：

    docker compose --profile rag down

不要使用 docker compose down -v，否则会删除本地数据库卷。

## 最小验收

- postgres 容器状态为 healthy。
- PostgreSQL 可以接受 psql 连接。
- vector 扩展可以创建并查询版本。
- 删除容器后重新启动，数据卷仍然存在。
- 未启动 rag profile 时，现有 TradingAgents 服务行为不变。

## 当前结果

已完成 Compose 配置和静态关键字段检查。当前 WSL 没有 Docker CLI，因此尚未实测容器启动、healthy 状态和 vector 扩展版本；这不是代码测试通过的结果，必须在启用 Docker Desktop WSL 集成后补验。

## 设计取舍

没有把 PostgreSQL 连接代码或 Python 驱动加入本工单，因为文档表和数据库访问层属于后续 R-03。没有加入 Redis，因为当前只有本地单机 RAG 基础设施，没有缓存、限流或异步任务需求。

## 30 秒面试答案

我把 PostgreSQL + pgvector 作为 RAG 的长期数据底座，但放在独立的 rag Compose profile 中，避免影响原有本地 Agent 流程。数据库使用持久卷保存数据，用 pg_isready 做健康检查，密码通过环境变量注入。当前工单只完成基础设施，下一步才建立 documents 和 document_chunks 表。

## 限制与下一步

当前未验证 Docker 运行时状态，也没有建表。下一步是 R-03：建立 documents、document_chunks、ingestion_runs 三张表和必要索引。
