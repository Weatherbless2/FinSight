# R-06/R-07：OpenSearch 索引与投影实施记录

`tradingagents/rag/opensearch.py` 新增 `OpenSearchClient`，提供集群健康检查、索引创建/删除、NDJSON bulk upsert 和查询请求。`build_chunk_projection()` 把 PostgreSQL 已验证的 Chunk 转为可重建投影，使用 `chunk_id` 作为 OpenSearch `_id`，保留 ticker、published_at、available_at、tenant、ACL、content_hash、模型版本、向量维度和 index_version。BM25/KNN 两路统一使用 `available_at <= trade_date`，published_at 只作为展示和审计字段。

新增 `scripts/bootstrap_opensearch.py`，可读取 `data/processed_documents/*.chunks.jsonl`，按批次创建 `rag-chunks-v1` 索引并写入 BM25 字段；Embedding 服务可用后可以在同一投影中填充 1024 维 BGE-M3 向量。查询构造器继续强制 ticker、`published_at <= trade_date`、tenant 和 ACL 过滤，用户文本不拼接进 DSL。

验证：`tests/test_rag_opensearch.py` 和 `tests/test_bootstrap_opensearch.py` 覆盖 mapping、过滤、维度、投影、bulk 请求体和索引重建，共 22 项组合测试通过；Ruff 通过。真实 OpenSearch 运行验证因 Docker Registry 当前无法拉取镜像而未完成，未将模拟客户端结果写成真实 Recall/P95。
