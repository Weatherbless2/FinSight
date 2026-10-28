# RAG Data Contract v1

本契约定义 R-00 的稳定标识、数据实体和接口边界。字段以逻辑类型描述，具体数据库类型由迁移实现；兼容新增字段采用可选/默认值，新模型和新索引使用显式版本字段。

## 核心实体

| 实体 | 主键 | 必需字段 | 来源与职责 |
| --- | --- | --- | --- |
| documents | document_id | ticker、document_type、title、source_url、source_hash、published_at、available_at、language、storage_bucket、object_key、object_version、ingestion_status | PostgreSQL 保存可信文档元数据；MinIO 对象由 object_key 与 object_version 定位 |
| document_chunks | chunk_id | document_id、ordinal、section、page_start/page_end、char_start/char_end、token_count、content、content_hash、ticker、published_at、tenant_id、acl_tags | PostgreSQL 保存唯一可信 Chunk 原文及引用位置；OpenSearch 只保存可重建投影 |
| embedding_runs | run_id | document_id、chunk_id 范围或批次、provider、model_name、model_version、dimensions、content_hash、status、attempt_count、started_at、finished_at、error_code | 记录向量化批次状态；成功状态必须与写入的模型版本和维度一致 |
| retrieval_events | event_id | run_id、trace_id、query_hash、ticker、trade_date、strategy、index_version、filters_applied、candidate_chunk_ids、latency_ms、result_count、created_at | 记录检索审计与质量数据；不得记录 API Key、凭证或不必要的原始查询正文 |

## 状态和约束

- 文档处理状态：discovered、stored、parsed、chunked、indexed、failed。每次变更记录时间和错误摘要。
- Embedding 状态：pending、running、succeeded、failed。失败可重试，状态不代表向量已进入正确索引；索引状态单独记录。
- published_at 必须参与历史时点约束；检索条件必须保证 published_at <= trade_date。最终证据在 PostgreSQL 回读时再次校验。
- tenant_id 与 acl_tags 在检索前过滤，回读后复核；缺少权限上下文时拒绝访问。
- source_hash 与 content_hash 使用 SHA-256 小写十六进制。document_id 和 chunk_id 对同一输入及版本保持稳定。
- Chunk 的字符区间采用清洗后规范文本的 0-based 半开区间 [char_start, char_end)，页码从 1 开始；未知页码使用空值，不编造位置。
- OpenSearch 写入/更新使用 chunk_id 幂等键；删除或重建索引不删除 PostgreSQL 原文。
- BGE-M3 v1 向量 dimensions 必须为 1024。1536 维旧数据与新版本隔离，禁止零填充、截断或跨模型比较。

## 七个核心接口

| 接口 | 输入 | 输出 | 失败语义 |
| --- | --- | --- | --- |
| Storage | 原始文件、来源、文档元数据 | bucket/key/version/hash 与存储状态 | 保留源文件或明确失败；数据库状态不得假报成功 |
| Parsing | 对象版本、解析器配置 | 带页码/表格位置的 ParsedDocument、解析版本与警告 | 失败状态可重试或转人工复核 |
| Chunking | ParsedDocument、切分配置 | 稳定 chunk_id、正文、章节、页码/字符位置 | 输入无有效文本时失败，不产生伪成功 Chunk |
| Embedding | 文本批次、model/version/dimensions | 每项向量和状态 | 校验批量长度、维度、有限数值；失败项可恢复 |
| Indexing | Chunk 标识、可检索字段、向量、index_version | bulk 结果和索引状态 | 部分失败按 chunk_id 重试；不改 PostgreSQL 事实记录 |
| Retrieval | ticker、trade_date、权限、query、strategy/top_k | chunk_id、rank、来源路、score、index_version | 依赖失败明确返回不可用状态，不把空结果伪装为证据不足 |
| Agent Search | 已校验查询与检索结果 | evidence_set、引用和结构化状态 | 无证据/过滤后无证据时返回可解释拒答，禁止自由补造 |

## 搜索投影字段

OpenSearch 文档至少包含 chunk_id、document_id、ticker、published_at、tenant_id、acl_tags、section、content、content_hash、embedding_model、embedding_version、embedding_dimensions、index_version。content 可按索引策略复制用于检索，但它不是引用事实来源；最终引用正文必须按 chunk_id 从 PostgreSQL 读取并复核。

## R-00 量化口径

- 架构决策覆盖率 = 已明确记录的必需决策项 / 冻结清单决策项总数。R-00 清单为 8 项：组件职责、可信源、检索归属、模型维度、版本隔离、Agent 访问边界、观测/密钥边界、回滚/切换门槛。
- 核心实体覆盖率 = 有主键、必需字段和职责的数据实体数 / 4。
- 核心接口覆盖率 = 明确输入、输出、失败语义的接口数 / 7。
- 目标均为 100%。覆盖率只证明规格已定义，不表示运行组件已部署或运行质量达标。
