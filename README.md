# FinSight

FinSight 是一个面向金融研究的多智能体分析平台。系统把行情、技术指标、新闻、宏观数据和 SEC 财报统一接入知识库，再由 LangGraph 编排基本面分析、市场分析、情绪分析、研究辩论、交易计划和风险复核，在 Web 工作台中展示带证据引用的研究结果。

## 核心流程

```text
股票代码 + 分析日期 + 研究问题
                |
                v
       SEC 文档发现与增量入库
                |
                v
       清洗 -> Chunk -> Embedding
                |
                v
    PostgreSQL + pgvector / OpenSearch
                |
                v
       关键词 / 向量 / Hybrid 检索
                |
                v
       EvidenceBundle 证据约束
                |
                v
       基本面 Agent + ToolNode
                |
                v
      多智能体研究与风险复核
                |
                v
        模拟评级与研究报告
```

分析请求包含股票代码、分析日期和研究问题。检索层按股票代码与 `available_at` 过滤证据，返回文档、日期、Chunk、来源地址和 Trace 信息；基本面 Agent 通过统一检索工具读取证据并生成报告。固定 LangGraph 图负责角色之间的顺序和状态传播，局部 ToolNode 循环负责模型选择工具和接收工具结果。

## 已实现能力

- **多智能体工作流**：LangGraph 编排分析师、研究员、交易员、风险角色和组合经理，使用中心状态传递消息、报告章节、辩论轮次和交易计划。
- **金融数据接入**：行情、技术指标、新闻、宏观数据、SEC 财报和公告进入统一分析链路；股票代码、日期、指标和财报参数使用 Pydantic 校验。
- **SEC 文档流水线**：完成财报发现、下载、哈希校验、正文清洗、章节切分、元数据保存和增量入库任务。
- **PostgreSQL RAG**：PostgreSQL 保存文档、Chunk、全文索引、Embedding 状态和向量，pgvector 执行向量相似度检索。
- **OpenSearch 检索路径**：提供对象存储、索引初始化和 OpenSearch Hybrid 检索适配，服务可通过环境变量选择 PostgreSQL 或 OpenSearch。
- **检索策略**：关键词、向量和 Hybrid 三种策略统一返回 `EvidenceBundle`，支持日期边界校验、引用校验、重排、上下文压缩和缓存。
- **在线兜底**：本地知识库没有命中时可启用 SEC 在线检索，响应中记录实际数据源、请求策略和回退原因。
- **评测与观测**：记录 Recall@5、MRR、引用覆盖率、未来证据泄露率、P95 延迟、检索 Trace、Embedding 状态和任务状态。
- **服务化工作台**：FastAPI 提供健康检查、覆盖范围、文档检索、基本面 Agent 报告和 SEC 增量入库接口；React + TypeScript 前端展示证据、评级、报告章节、任务状态和股票覆盖范围。
- **异步执行**：默认使用进程线程池执行入库任务，并提供 Redis + Celery 执行器；Airflow DAG 编排定时发现、下载、解析、Embedding 和入库流程。
- **持续交付配置**：仓库包含 Docker Compose、数据库迁移、部署配置、数据契约和测试契约，支持从本地开发环境运行到服务化部署。

## 项目结构

```text
tradingagents/                 核心 Python 包
  agents/                      分析师、研究员、交易员、风险和管理角色
  graph/                       LangGraph 图、路由、状态传播和检查点
  dataflows/                   行情、新闻、宏观和供应商数据流
  llm_clients/                 多模型和 OpenAI-compatible 客户端
  rag/                         文档、解析、Chunk、Embedding、检索和证据校验
  observability/               运行事件、计时、指标和观测辅助代码
  tasks/                       财报异步入库和 Celery 任务入口

data/raw_documents/            SEC 原文和文档元数据
data/processed_documents/      清洗后的 Chunk JSONL
db/migrations/                 PostgreSQL、pgvector 和任务表迁移
deploy/                        Airflow 和部署配置
scripts/                       财报采集、入库、Embedding、评测和演示脚本
frontend/                      React + TypeScript + Vite 前端
docs/                          架构、数据契约、评测报告和运行记录
tests/                         Agent、RAG、工具、路由和数据链路测试
reports/                       运行日志和研究报告
results/                       RAG 评测原始结果和摘要
```

## 技术栈

- Python 3.12、LangChain、LangGraph、Pydantic
- FastAPI、Uvicorn、SQLAlchemy
- PostgreSQL 16、pgvector、全文检索
- OpenSearch、MinIO、Redis、Celery、Airflow
- Ollama `nomic-embed-text` 或 BGE-M3 TEI Embedding 服务
- OpenAI-compatible LLM 网关
- React、TypeScript、Vite、Lucide React
- pytest、Ruff、Docker Compose

## 快速启动

### 1. 准备 Python 环境

```bash
git clone git@github.com:Weatherbless2/FinSight.git
cd FinSight
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

从 `.env.example` 复制本地配置，填写模型、数据库、RAG 和 Embedding 服务地址。

### 2. 启动 PostgreSQL + pgvector

```bash
docker compose --profile rag up -d postgres
docker compose --profile rag ps postgres
```

启动 FastAPI 服务：

```bash
export TRADINGAGENTS_SEARCH_BACKEND=postgres
uvicorn scripts.run_rag_demo:app --host 127.0.0.1 --port 8000
```

### 3. 启动 React 前端

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

访问：

```text
http://127.0.0.1:5173/              React 投研工作台
http://127.0.0.1:8000/docs          FastAPI 接口文档
http://127.0.0.1:8000/health        服务健康检查
http://127.0.0.1:8000/api/coverage  PostgreSQL 知识库覆盖范围
```

### 4. 启用 OpenSearch 全链路

```bash
docker compose --profile rag up -d postgres minio opensearch
export TRADINGAGENTS_SEARCH_BACKEND=opensearch
export OPENSEARCH_URL=http://127.0.0.1:9200
export OPENSEARCH_INDEX=rag-chunks-v1
python scripts/bootstrap_opensearch.py
```

BGE-M3 TEI 服务独立启动，地址通过 `BGE_M3_TEI_URL` 配置。OpenSearch 适配保留 PostgreSQL 作为本地知识库和数据回退源。

## 开发验证

```bash
.venv/bin/ruff check tradingagents tests
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_real_rag_eval.py
```

RAG 评测结果写入 `results/rag_eval/rag-evaluation.json` 和 `results/rag_eval/rag-evaluation.md`，HTML 报告位于 `docs/R-12-D-evaluation-report.html`。

## 数据与接口契约

RAG 数据契约位于 `docs/contracts/rag-data-contract-v1.md`，架构图位于 `docs/contracts/rag-architecture-v1.mmd`。数据库迁移位于 `db/migrations/`，包含文档、Chunk、向量、任务和评测所需的表结构。

## 许可证和上游致谢

FinSight 基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 继续开发，仓库保留上游许可证和引用信息，详见 [CHANGELOG.md](CHANGELOG.md)、[LICENSE](LICENSE) 和 `assets/`。
