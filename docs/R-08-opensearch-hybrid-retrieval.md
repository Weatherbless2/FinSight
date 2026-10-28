# R-08：OpenSearch Hybrid 检索接入

新增 `tradingagents/rag/opensearch_retrieval.py` 和 `create_opensearch_retriever()`。关键词路径使用 OpenSearch BM25，向量路径使用 BGE-M3 1024 维 k-NN，Hybrid 路径按 `weight / (rrf_k + rank)` 计算两路贡献。OpenSearch 只返回候选 `chunk_id` 和分数，适配器随后调用 `PostgresRetriever.hydrate_hits()`，按参数化 `IN` 查询从 PostgreSQL 读取正文、来源、Ticker、published_at 和 available_at，再次执行日期和股票边界检查。

FastAPI RAG 演示支持 `TRADINGAGENTS_SEARCH_BACKEND=opensearch` 和 `OPENSEARCH_URL`/`OPENSEARCH_INDEX` 配置，默认继续使用 PostgreSQL 回滚路径。新增测试覆盖候选融合、分数、权重、权威数据 hydration 和 SQL 参数化。真实 OpenSearch 服务仍待镜像可拉取、索引构建和固定评测集复测后再切换为默认路径。
