# ADR-002：TradeAgent RAG 最终架构与迁移边界

## 状态

采纳，2026-10-27。此决策落实 R-00 的组件职责、可信数据边界、模型版本和回滚规则。R-00 完成架构冻结，不表示后续工单组件已部署或已经切换生产流量。

## 背景与当前实现

当前仓库已经有金融文档元数据契约、SEC 文档发现和下载、HTML 解析与清洗、Chunk 切分、PostgreSQL 文档与片段入库、1536 维 pgvector Embedding、关键词/向量/Hybrid 检索、证据校验、LangGraph 基本面工具、异步入库、离线评测和 FastAPI 演示服务。代码主要位于 tradingagents/rag/，数据库迁移位于 db/migrations/，原始与处理后样本位于 data/raw_documents/ 和 data/processed_documents/。

本次目标架构规定 MinIO、Airflow、PostgreSQL、OpenSearch、BGE-M3/TEI、BGE-Reranker-v2-m3、LangGraph、FastAPI、Redis、OpenTelemetry/Prometheus/Grafana/Langfuse/Vault。当前实现和目标架构存在存储、检索引擎、Embedding 模型与维度、解析对象、调度方式的差异。差异不通过一次性切换解决；R-01 至 R-17 逐项补齐，在迁移验收通过前保留现有 PostgreSQL + pgvector 检索路径。

## 冻结组件职责

| 层 | 冻结组件 | 唯一职责 | 数据边界 |
| --- | --- | --- | --- |
| 原始文档与调度 | MinIO、Airflow | 保存不可变原始文件；安排解析、Embedding、索引任务及失败重试 | MinIO 保存源文件对象；任务调度不成为业务数据源 |
| 可信记录 | PostgreSQL | 保存文档、Chunk 原文、版本、ACL、发布日期、处理状态与审计关系 | 所有引用最终以 PostgreSQL 校验后的记录为准 |
| 搜索 | OpenSearch | 同一集群承担 BM25 与向量候选召回 | 索引是可重建的搜索投影，不是原文事实源 |
| 向量生成与精排 | BGE-M3 经 TEI；BGE-Reranker-v2-m3 | 生成 1024 维文档/查询向量；对候选 Chunk 重排 | 模型名、模型版本、维度、索引版本显式记录 |
| Agent 与服务 | LangGraph、LiteLLM、FastAPI、Redis | 受控工作流、模型网关、HTTP 接口、短期缓存和异步任务状态 | Agent 只经白名单工具访问已验证证据 |
| 观测与密钥 | OpenTelemetry、Prometheus、Grafana、Langfuse、Vault | 追踪、指标、LLM 调用观测、密钥托管 | 不记录密钥；查询正文按最小必要原则记录或使用哈希 |
| 部署与质量 | Docker Compose、Kubernetes、离线评测与 CI | 本地开发、生产部署、质量门禁、灰度和回滚 | 没有真实规模瓶颈前不增加 Kafka 或 Milvus |

## 可信数据流

原始文件写入 MinIO 并取得对象版本与 SHA-256；Airflow 触发解析、清洗和结构化切分；解析文本、Chunk 原文和权限/日期元数据写入 PostgreSQL；BGE-M3/TEI 为 Chunk 生成 1024 维向量；索引任务将 chunk_id、检索字段、权限/日期字段与向量写入 OpenSearch。查询时 BM25 与向量检索都执行 ticker、trade_date、tenant/ACL 过滤，融合和重排后仅返回 chunk_id 及候选分数。服务层按 chunk_id 回 PostgreSQL 读取原文并重新校验日期、权限、股票和引用位置，合格证据才可进入 AgentState 与回答。

## 版本与兼容规则

1. BGE-M3 的目标维度固定为 1024。禁止把较短向量补零以伪装成另一模型的维度。
2. 旧有 1536 维 pgvector 数据及当前 Ollama/OpenAI-compatible provider 保留为旧版本命名空间；新模型不得覆盖或混入旧向量。
3. Embedding 记录至少包含 provider、model_name、model_version、dimensions、输入内容哈希、状态和生成时间。向量索引名包含模型/维度或明确 index_version。
4. document_id、chunk_id、source_hash 和 content_hash 提供稳定关联与幂等依据。搜索索引允许重建，PostgreSQL 与 MinIO 的关联可审计。
5. OpenSearch 成为默认查询路径前，必须完成双路结果对比、日期/权限边界测试、离线评测和回滚验证。过渡期间可以并行验证，但不能把未验收的路径宣称为完成。

## 迁移与回滚

迁移按工单顺序分阶段完成。保留当前 PostgreSQL + pgvector 查询实现作为回滚基线；OpenSearch 索引从 PostgreSQL 的已验证 Chunk 重建。切换前固定同一测试集与过滤条件，对比 Recall@K、MRR、引用覆盖、未来泄露、过滤错误和 P95。出现索引不一致、证据引用失败、未来泄露或权限边界错误时，关闭新检索路由并恢复旧路径；原始文件和可信 Chunk 不删除。模型迁移采用新字段和新索引，只有新版本全部通过验收后才允许停用旧向量。

## R-00 验收

- 组件职责表覆盖每个冻结组件且无双重可信事实源。
- documents、document_chunks、embedding_runs、retrieval_events 四类核心实体均有字段契约。
- Storage、Parsing、Chunking、Embedding、Indexing、Retrieval、Agent Search 七个核心接口均有输入、输出和失败语义。
- 所有检索结果都必须以 chunk_id 回查 PostgreSQL。
- 模型名、版本、维度及索引版本不得隐式混用。
- 架构图、契约、实现顺序和回滚条件相互一致。

## 决策证据

R-00 实施详情、量化覆盖率和测试命令记录在 docs/R-00-final-architecture-and-contract.md 及 docs/implementation/TradeAgent_RAG_Workorder_Implementation.docx。后续工单须更新同一实施记录，不得以本 ADR 代替真实部署或运行验收。
