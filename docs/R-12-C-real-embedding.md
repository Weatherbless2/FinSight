# R-12-C：真实 Embedding

## 面试问题

真实 Embedding API 调用失败、返回错误维度或模型升级时，系统如何保证向量库不被脏数据污染，并且能定位和重试失败片段？

## 实现

1. tradingagents/rag/embeddings.py 保留统一 EmbeddingProvider，新增 OllamaEmbeddingProvider。
2. 聊天模型继续使用 http://gptch.cloud/v1；RAG Embedding 使用本地 Ollama。
3. Ollama 模型为 nomic-embed-text，原生输出 768 维。
4. OllamaEmbeddingProvider 将 768 维向量补齐到 PostgreSQL VECTOR(1536)；零填充不会改变前 768 维向量之间的余弦相似度。
5. embed_chunks() 按批次发送文本，调用失败时整批生成 failed + retryable 结果。
6. validate_embedding_vector() 拒绝错误维度、非有限数和全零向量。
7. db/migrations/002_embedding_metadata.sql 增加 provider、model、version、status、error、embedded_at。
8. PostgresChunkRepository.update_embeddings() 只把成功向量写入；失败记录只更新诊断字段。
9. scripts/embed_postgres_chunks.py 默认读取本地 Ollama 配置，可通过 --provider openai 切换到 OpenAI-compatible 服务。

## 安装和运行

~~~bash
curl -fsSL https://ollama.com/install.sh | sh
systemctl status ollama
ollama pull nomic-embed-text
~~~

项目配置：

~~~env
TRADINGAGENTS_LLM_BACKEND_URL=http://gptch.cloud/v1
TRADINGAGENTS_EMBEDDING_PROVIDER=ollama
OLLAMA_EMBEDDING_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
~~~

执行：

~~~bash
cd /root/projects/TradingAgents
.venv/bin/python scripts/embed_postgres_chunks.py   --database-url postgresql+psycopg://tradingagents:tradingagents_dev_only@127.0.0.1:55432/tradingagents   --provider ollama   --batch-size 16   --max-retries 2   --timeout-seconds 120
~~~

查看结果：

~~~bash
docker exec -i tradingagents-postgres-1 psql   -U tradingagents   -d tradingagents   -c "select embedding_status, count(*) from document_chunks group by embedding_status;"
~~~

## 实测结果

- Ollama 版本：0.34.2。
- nomic-embed-text:latest 已下载，模型大小约 274 MB。
- /api/embed 返回 200，原生向量维度为 768。
- 首个 Chunk：1 条成功，耗时 87.16 ms。
- 剩余 329 条：全部成功，批量大小 16，总耗时 44.435 s。
- PostgreSQL：330 条 succeeded，embedding IS NULL 为 0。
- 数据库中 330 条向量的 vector_dims(embedding) 均为 1536。
- 本地契约测试：7 passed；Ruff：All checks passed。
- 这些数据证明向量生成和入库链路可用，但还没有证明检索 Recall、MRR 或 Agent 最终回答质量提升。

## 通俗解释

gptch.cloud 负责让 Agent 读懂问题并生成文字；Ollama 负责把财报片段转换成数字向量。两者是两个不同岗位，不是同一个 GPT 接口。

本地模型实际输出 768 个数字，项目在后面补 768 个 0 存进数据库的 1536 维列。这样不需要重建数据库，同时保留了模型原本的语义相似关系。

## 30 秒面试答案

我没有把聊天模型误当成 Embedding 模型，而是把职责拆开：聊天推理走 OpenAI-compatible GPT 网关，财报向量化走本地 Ollama nomic-embed-text。Provider 会做批量调用、超时重试、原生维度校验和失败落库；本次 330 个真实 Chunk 全部生成并写入 PostgreSQL，最终数据库中 330 条向量均为 1536 维。下一步再用这些真实向量做四策略 Recall、MRR 和 P95 评测。
