# RAG、数据库与服务化工单路线

本路线建立在当前 TradeAgent 的实际基线之上：已有 LangGraph 固定工作流、分析师局部工具循环、结构化金融 API、SQLite 检查点和本地行情缓存；尚未实现文档知识库、检索增强生成、PostgreSQL 文档存储、向量索引或 Redis 运行时。

## 总体原则

- 先建立评测集，再实现检索；没有基线就不能声称“提升了准确率”。
- RAG 只先接入基本面 Agent，其他 Agent 消费带来源的基本面报告。
- PostgreSQL + pgvector 负责长期文档、元数据、片段和向量；Redis 仅在服务化后按需承担缓存、限流或任务队列。
- `available_at <= trade_date` 是金融日期硬规则，不能由模型覆盖。
- 所有 Agentic Retrieval 都必须有调用轮数、工具次数、重复查询和 Token 预算上限。
- 主线工单只做最小冒烟验证：通常 1 条主路径加 1 条关键边界；不要在每张工单中提前建设完整评测体系。
- 完整的 Recall@K、MRR、引用覆盖率、P95 和 Token 对比集中放到 R-12，前置工单只准备输入和接口。
- 每张工单结束时必须向用户说明：做了什么、目的是什么、结果是什么、仍有限制和下一步。

## 工单总表

| ID | 阶段 | 依赖 | 主要内容 | 预期效果与验收 |
| --- | --- | --- | --- | --- |
| R-00 | 评测基线 | 无 | 3 只股票、12 个文档元数据样本、30 条问题；覆盖事实、比较、推理、未来边界、证据不足；记录标准文档和章节。只做清单加载和日期边界冒烟验证。 | 30 条问题固定；每类 6 条；未来信息题无标准证据；不运行真实检索。 |
| R-01 ✅ | 文档契约 | R-00 | 固定 `document_id/ticker/document_type/title/source_url/source_hash/published_at/available_at/fiscal_period/period_end/language` 和 `chunk_id/ordinal/section/page/text/token_count`。 | 已完成：片段可按股票、日期、类型和来源追溯；未知字段拒绝。 |
| R-02 ⚠️ | PostgreSQL 基础设施 | R-01 | Docker PostgreSQL、pgvector、健康检查、持久卷、连接配置和测试库。 | 配置已完成；数据库启动、healthy 状态和向量扩展需在 Docker 可用后补验。 |
| R-03 ⚠️ | 数据表和索引 | R-02 | `documents`、`document_chunks`、`ingestion_runs`；唯一哈希；股票、日期、类型普通索引；全文索引；向量索引。 | SQL 迁移和静态校验已完成；实际数据库应用需在 Docker 可用后补验。 |
| R-04 ✅ | 原始文档导入 | R-03 | 优先 SEC EDGAR HTML 和公司 IR 公告；保存原文、来源、下载时间、哈希、状态和失败原因。 | 已完成：具备单文档公开 URL 下载、原文落盘、SHA-256 和成功/失败清单；批量调度和重试后置。 |
| R-05 ✅ | 解析清洗 | R-04 | 保留标题、段落、表格标题、页码/位置；删除页眉页脚、导航、重复免责声明和乱码；金额、单位、百分号不丢失。 | 已完成 HTML 解析和清洗；PDF、OCR 和真实文档抽样后置。 |
| R-06 ✅ | Chunk 切分 | R-05 | 按章节和段落边界切；普通片段目标 350～550 tokens、硬上限 700、重叠 60～80 tokens；表格独立切分并保留表头；`chunk_id` 稳定。 | 已完成：无超长普通片段；每片段保留章节、位置和稳定 ID；表格独立切分并重复表头。 |
| R-07 ✅ | 向量与全文索引 | R-06 | Embedding Provider 和模型版本可配置；片段同时生成向量和全文索引；失败可重试并留状态。 | 已完成 Provider 抽象、1536 维契约、确定性 Mock 和可重试失败状态；真实向量入库与全文索引写入留给后续数据库验收。 |
| R-08 ✅ | Hybrid Retrieval | R-07 | 先过滤股票、日期、类型；向量 Top-20 与关键词 Top-20 用 RRF 融合，返回 Top-10；第一版不急于加入 Reranker。 | 已完成内存版过滤、双路候选和 RRF 返回契约；未来文档边界已测试。真实 PostgreSQL 检索和 Recall@5 对比留给 R-12/环境验收。 |
| R-09 ✅ | 引用与日期校验 | R-08 | `EvidenceBundle` 包含 `chunk_id/document_id/source_url/available_at/section/text_excerpt`；代码校验股票、日期、来源和引用存在。 | 已完成证据包、索引逐字段对照和未来/跨股票/缺失 Chunk/篡改正文拒绝；真实数据库链路留待环境验收。 |
| R-10 ✅ | 基本面 Agent 接入 | B-02、R-09 | 增加 `search_financial_documents()`；Agent 根据问题选择 API、RAG 或两者；返回统一 `success/data/error_code/retryable/source/timestamp`。 | 已完成基本面 ToolNode 接入、API/RAG/混合路由和统一错误返回；真实 RAG 服务通过依赖注入，未配置时明确返回可重试错误。 |
| R-11 ✅ | 受约束 Agentic Retrieval | B-04、D-01、R-10 | 最多 2 轮、3 次检索、每轮最多 6 个片段；查询指纹去重；限制字符/Token；证据不足时停止或改写查询。 | 已完成有限运行器、查询指纹、轮次/查询/片段/上下文预算和 Trace；重复 Query、检索异常和证据不足都会明确停止。 |
| R-12 ✅（评测器） | 离线评测回归 | R-00、R-08、R-11 | 集中比较关键词、向量、Hybrid、Agentic 四种方案的 Recall@5、MRR、引用覆盖率、无依据结论率、未来泄露率、P95、Token。 | 已完成统一评测输入、指标计算、未来泄露检查和 JSON/Markdown 报告生成；真实数据执行拆分为 R-12-A～R-12-D。 |
| R-12-A ✅ | 真实文档 Chunk | R-04、R-05、R-06 | 下载少量公开 SEC HTML，校验原文哈希，解析清洗并生成 Chunk JSONL。 | 已完成 3 份真实文档、330 个 Chunk；发现 9 个目录/页码类小片段，需后续清理。 |
| R-12-B ✅ | PostgreSQL 实际入库 | R-02、R-03、R-12-A | 启动 pgvector，执行迁移，把真实文档元数据、Chunk 和全文字段写入数据库；使用 SQLAlchemy 仓储实现批次校验、事务、失败记录和幂等导入。 | 已完成：`vector/pgcrypto` 扩展存在，3 份文档、330 个 Chunk、330 个 `content_tsv` 已真实入库；重复导入插入数为 0，未来向量由 R-12-C 写入。 |
| R-12-C ✅ | 真实 Embedding | R-07、R-12-B | 聊天推理继续使用 gptch.cloud，RAG 向量化使用本地 Ollama nomic-embed-text；按批生成、校验原生 768 维并适配到 VECTOR(1536)，写入 provider/model/version/status/error。 | 已完成：Ollama 0.34.2，330 个真实 Chunk 全部成功；330 条向量均为 1536 维，embedding IS NULL=0；单条 87.16ms，剩余 329 条批量 16，总耗时 44.435s。 |
| R-12-D | 四策略真实评测 | R-08、R-11、R-12-C | 对 30 道固定问题运行关键词、向量、Hybrid、Agentic 四种策略，生成真实指标报告。 | 产生真实 Recall@5、MRR、引用覆盖率、未来泄露率、P95 和 Token 对比；未来泄露率必须为 0。 |
| R-13 ✅（检索工具层） | Trace 与成本 | D-01、R-11 | 记录 `run_id`、查询指纹、过滤条件、候选数量、引用、调用次数、耗时、Embedding 模型、Token/成本可用性、错误码；敏感数据脱敏；接入基本面 Agent。 | 已完成 PostgreSQL RAG 适配器、证据校验、JSON Trace、基本面服务注入和真实工具层冒烟；完整 LLM 回答级 Token/成本仍需带 usage 的模型运行补齐。 |
| R-15-A ✅ | 结构化报告契约 | R-13 | 将基本面 Agent 的 Markdown 结果包装为 `rating/summary/sections/raw_markdown`；保留原文用于审计，不让前端依赖标题解析。 | `/api/agent` 返回结构化报告和原始报告；页面可分别展示结论、财务、风险和展望。 |
| R-15-B ✅（第一版） | FastAPI 报告工作台 | R-15-A | 保留 FastAPI 演示入口，改成评级卡、运行指标、报告章节、原始报告折叠和财报覆盖区域；前端不再直接堆整段 Markdown。 | 已完成可运行的结构化页面；React + TypeScript + Vite 迁移列为后续前端工单。 |
| R-16 ✅（接口层） | 本地优先、SEC 在线兜底 | R-08、R-13 | 本地 PostgreSQL 无命中且显式开启开关时，访问 SEC 官方来源，在内存中解析、切分、向量化并返回；在线结果标记 `source=online_sec`、`persisted=false`。 | 未覆盖股票可以临时获得官方材料；默认关闭，避免用户请求隐式触发网络和高延迟。 |
| R-17 ✅（第一版） | 异步增量入库任务 | R-14、R-16 | 新增 `ingestion_jobs`；FastAPI 返回 `job_id`，后台执行发现、下载、解析、Chunk、PostgreSQL 幂等写入和 Ollama 向量化；支持状态查询。 | 请求不被长任务阻塞；任务有 `queued/running/succeeded/failed` 和错误信息；当前执行器为进程内线程池。 |
| R-18 ✅ | React 服务化前端 | R-15-B | 使用 React + TypeScript + Vite；报告、证据、任务进度和覆盖范围通过 FastAPI JSON 接口渲染。 | 已完成前端源码、类型化 API、Vite 代理和响应式布局；Node 18 兼容版已构建成功，Vite 开发服务已启动。 |
| R-19 ✅（代码） | Redis/Celery Worker | R-17、R-18 | 增加 Redis Compose 服务、Celery 任务入口、延迟投递开关、失败回写和重试配置；默认仍使用线程池。 | 已完成可选 Celery 执行器代码和 Docker 配置；Redis 容器与 Worker 的真实运行验收待安装依赖后完成。 |
| R-20 | SEC 定时发现 | R-19 | 使用 Celery Beat 或 APScheduler 定期发现关注股票的新 10-K、10-Q、8-K；以 accession number、source_hash 和 document_id 去重。 | 新财报自动进入增量任务，不重复下载，失败可重试。 |
| R-21 | 覆盖范围与增量指标 | R-17、R-20 | 记录每只股票最新可用日期、文档数、Chunk 数、向量成功率、最近同步状态和失败原因。 | 页面能回答“哪些股票可分析、数据新到哪天、为什么失败”。 |
| R-22 | 本地与在线兜底评测 | R-16、R-20 | 比较本地命中率、在线兜底成功率、P95 延迟、下载失败率、向量失败率和入库耗时。 | 证明在线覆盖率提升的同时没有把延迟和稳定性问题隐藏起来。 |
| S-01 | 服务化存储 | F-01、R-13 | PostgreSQL 保存用户、任务、报告、文档和索引版本；任务状态为 `pending/running/succeeded/failed`。 | 长任务可查询、失败可定位、报告可回溯。 |
| S-02 | Redis 条件引入 | S-01 | 只用于热点检索缓存、限流、异步队列；Key 包含 `index_version/ticker/trade_date/document_type/query_hash`；不作为事实库。 | 重复查询减少数据库和 Embedding 调用；索引版本更新可自动失效。 |

## Chunk 专项规则

| 内容 | 规则 | 目的 |
| --- | --- | --- |
| 管理层讨论 | 按章节和自然段切分，片段前保留章节名 | 不混淆增长原因、展望和风险 |
| 财务表格 | 一张表或一个逻辑表区块独立成片段，保留表头、单位和期间 | 防止数字失去语义 |
| 风险因素 | 一个风险主题或连续 2～4 段为片段 | 保留限定条件和风险上下文 |
| 前瞻性声明 | 独立切分并增加前瞻性标记 | 不把预测当作历史事实 |
| 页眉页脚与目录 | 删除或去重 | 减少无效召回 |
| 超长章节 | 只在段落边界切分，并保留 60～80 tokens 重叠 | 控制长度并减少语义截断 |

## 工单交付格式

每张完成工单都必须记录：

```text
问题：面试官会怎么问？
做了什么：修改了哪些代码、文档或测试？
目的：解决哪个业务或工程问题？
WSL 项目修改：具体文件、函数、关键代码和中文注释。
结果：最小测试的通过/失败数量、耗时和输入规模；完整指标只在 R-12 记录。
取舍：为什么选择当前方案？
限制：当前还不能证明什么？
面试答案：30 秒可复述版本。
下一步：下一张依赖工单。
```
