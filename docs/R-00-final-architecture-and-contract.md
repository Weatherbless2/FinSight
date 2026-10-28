# R-00：冻结架构与数据契约

## 状态

已完成规格冻结。当前代码已经提供 MinIO 对象存储适配器、OpenSearch HTTP/index 投影适配器和 BGE-M3/TEI Provider；MinIO、OpenSearch、TEI 的真实容器运行验收仍由部署环境完成。现有 PostgreSQL + pgvector 链路保留为迁移期间的可运行基线。

## 当前项目基线

仓库已有 PostgreSQL + pgvector 文档/Chunk 入库、1536 维 Embedding、关键词/向量/Hybrid 检索、证据校验、LangGraph 基本面工具、SEC 采集解析、异步入库、离线评测及 FastAPI 演示；本轮补充了 MinIO、OpenSearch 和 BGE-M3/TEI 的客户端与 Compose 配置。Airflow 调度编排尚未实现。当前 RAG 实现集中在 tradingagents/rag/；迁移脚本在 db/migrations/；原始/处理后样本分别在 data/raw_documents/ 和 data/processed_documents/。仓库工作区原有 embeddings.py 和测试样本未提交改动保留不动。

## 本工单冻结的边界

1. PostgreSQL 是文档、Chunk、权限、发布日期、处理状态和引用内容的可信数据源。
2. OpenSearch 统一承担 BM25 与向量候选召回；其数据是按 chunk_id 可重建的投影。
3. BGE-M3 经 TEI 输出 1024 维向量；不补零到旧 1536 维，也不覆盖旧向量。
4. 所有检索候选必须带 chunk_id；回到 PostgreSQL 读原文并复核股票、日期、权限及引用位置后才能交给 Agent。
5. Redis 仅缓存和跟踪异步状态，不承担长期事实记录；MinIO 保存不可变原始文件；Airflow 管调度和重试。
6. 新检索路径在 R-06 至 R-15 的索引、边界与离线评测门槛通过前，不替换当前 pgvector 路径。
7. 迁移失败时恢复 PostgreSQL + pgvector 查询路径；原始文档和可信 PostgreSQL 记录不删除。

## 字段与接口契约

完整字段表、状态语义、版本约束和 Storage / Parsing / Chunking / Embedding / Indexing / Retrieval / Agent Search 七个接口见 docs/contracts/rag-data-contract-v1.md。组件职责与数据路径见 docs/contracts/rag-architecture-v1.mmd；决策记录见 docs/ADR-002-rag-final-architecture.md。

关键实体为 documents、document_chunks、embedding_runs、retrieval_events。文档与 Chunk 使用稳定 ID 和 SHA-256 哈希；Embedding 记录 provider、model、version、dimensions、状态与重试信息；检索事件记录 query_hash、过滤条件、index_version、候选 ID、结果数与延迟，不写凭证。

## 实施与复核

本工单先完成决策与契约，不改写现有数据库结构、不安装或部署外部服务。后续工单按 R-01 至 R-17 顺序将当前 SEC/pgvector 实现与冻结目标逐步接通。每次切换都使用固定评测集对比 Recall@K、MRR、引用覆盖、无依据结论、未来泄露、过滤错误和 P95，并保留可回退路径。

量化结果、命令和验收证据记录在 docs/implementation/TradeAgent_RAG_Workorder_Implementation.docx。
