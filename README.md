# TradeAgent

TradeAgent 是一个面向金融研究和模拟决策的多智能体项目。它把股票行情、技术指标、新闻、宏观数据、财报和公告交给不同的分析角色处理，再经过多空研究、交易计划和风险复核，输出一份带运行信息的研究报告。

这个仓库的重点不是自动实盘交易，而是学习和展示 Agent 工程能力：工作流编排、工具调用、状态管理、RAG、数据入库、异步任务、可观测性、测试和前后端服务化。

> 仅用于研究、模拟决策和工程学习，不构成投资建议，也没有接入真实券商自动下单。

## 一句话理解

用户输入股票代码、分析日期和问题后，系统先按日期过滤可用财报，再从 PostgreSQL + pgvector 检索相关 Chunk；基本面 Agent 结合检索证据组织结论，LangGraph 负责控制多智能体流程，FastAPI 提供接口，React 页面展示证据、报告和任务进度。



### 已有真实结果

- RAG 评测报告：`docs/R-12-D-evaluation-report.html`。
- 固定样本评测中，向量检索 Recall@5 为 `100.00%`，Hybrid 为 `97.22%`，关键词检索为 `80.56%`。
- 四种策略的未来证据泄露率均为 `0%`。
- 评测记录了 MRR、引用覆盖率和 P95 延迟；关键词检索 P95 为 `6.990 ms`，向量检索 P95 为 `56.580 ms`，Hybrid P95 为 `55.803 ms`。
- 真实 Embedding 工单中，成功生成向量并写入 PostgreSQL，数据库向量维度为 1536。
- 真实基本面 RAG 运行记录在 `docs/R-13-postgres-rag-agent-trace.md`，其中明确区分了检索工具层已验证和完整多轮辩论仍存在的网关超时边界。



## 系统怎么工作

```text
股票代码 + 分析日期 + 研究问题
                |
                v
       本地 PostgreSQL 知识库
       按股票和 available_at 过滤
                |
                v
       关键词 / 向量 / Hybrid 检索
                |
                v
       EvidenceBundle 引用校验
                |
                v
       基本面 Agent + ToolNode 循环
                |
                v
       市场、情绪、新闻、基本面分析
                |
                v
       多空研究辩论 -> 交易计划
                |
                v
       风险复核 -> 模拟评级和研究报告
```

整体是固定的 LangGraph 工作流，保证流程可控；分析师内部保留有限工具调用循环，保证模型可以根据问题选择合适的数据工具。研究和风险辩论都有轮数上限，图执行也有递归限制，避免模型无限调用。

## 目录说明

```text
tradingagents/                 核心 Python 包
  agents/                      分析师、研究员、交易员、风险和管理角色
  graph/                       LangGraph 图、路由、传播和检查点
  dataflows/                   行情、新闻、宏观和供应商数据流
  llm_clients/                 多模型和 OpenAI-compatible 客户端
  rag/                         文档、解析、Chunk、Embedding、检索和证据校验
  observability/               运行事件、计时、指标和观测辅助代码
  tasks/                       财报异步入库和 Celery 任务入口

data/raw_documents/            SEC 财报原文和文档元数据
data/processed_documents/      清洗后的 Chunk JSONL
db/migrations/                 PostgreSQL、pgvector 和任务表迁移
scripts/                       财报采集、入库、Embedding、评测和演示脚本
frontend/                      React + TypeScript + Vite 前端
docs/                          工单、架构说明、评测报告和运行记录
skills/                        项目学习 Skill 及工单参考资料
tests/                         Agent、RAG、工具、路由和数据链路测试
reports/                       已保存的运行日志和研究报告
results/                       RAG 评测原始结果和 Markdown 摘要
```

## 关键技术栈

- Python 3.12、LangChain、LangGraph、Pydantic。
- FastAPI、Uvicorn、SQLAlchemy。
- PostgreSQL 16、pgvector、全文检索。
- Ollama `nomic-embed-text`：负责财报 Chunk 向量化。
- OpenAI-compatible LLM 网关：负责聊天推理，地址和模型通过环境变量配置。
- React、TypeScript、Vite、Lucide React。
- Redis、Celery：作为可选的异步任务执行器和后续缓存基础设施。
- pytest、Ruff、Docker Compose。

## 最快启动方式

### 1. 准备 Python 环境

```bash
git clone git@github.com:Weatherbless2/TradeAgent.git
cd TradeAgent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

配置文件模板是 `.env.example`。聊天模型、数据库、RAG 和 Ollama 地址都应该通过环境变量配置，不要把密钥写进代码。

### 2. 启动 PostgreSQL + pgvector

```bash
docker compose --profile rag up -d postgres
```

检查数据库：

```bash
docker compose --profile rag ps postgres
```

状态应为 `healthy`。如果要使用 Redis/Celery：

```bash
docker compose --profile rag up -d redis
```

### 3. 启动 FastAPI 演示服务

```bash
TRADINGAGENTS_ENABLE_POSTGRES_RAG=true \
uvicorn scripts.run_rag_demo:app --host 127.0.0.1 --port 8000
```

浏览器访问：

```text
页面：http://127.0.0.1:8000
接口文档：http://127.0.0.1:8000/docs
健康检查：http://127.0.0.1:8000/health
```

页面可以完成四件事：查看已接入股票，检索真实财报 Chunk，生成基本面 Agent 报告，以及创建新的 SEC 财报增量入库任务。

### 4. 启动 React 前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。Vite 会把 `/api` 和 `/health` 转发到 FastAPI 的 8000 端口。

## 常用验证命令

查看整体工作流：

```bash
grep -nE "StateGraph|add_node|add_edge|add_conditional_edges|ToolNode" \
  tradingagents/graph/setup.py \
  tradingagents/graph/trading_graph.py \
  tradingagents/graph/conditional_logic.py
```

运行完整测试：

```bash
.venv/bin/ruff check tradingagents tests
.venv/bin/python -m pytest -q
```

运行 RAG 评测：

```bash
.venv/bin/python scripts/run_real_rag_eval.py
```

评测结果位置：

```text
results/rag_eval/rag-evaluation.json
results/rag_eval/rag-evaluation.md
docs/R-12-D-evaluation-report.html
```

