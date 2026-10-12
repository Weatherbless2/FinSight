# TradeAgent

TradeAgent 是一个面向金融研究和模拟决策的多智能体项目。它把股票行情、技术指标、新闻、宏观数据、财报和公告交给不同的分析角色处理，再经过多空研究、交易计划和风险复核，输出一份带运行信息的研究报告。

这个仓库的重点不是自动实盘交易，而是学习和展示 Agent 工程能力：工作流编排、工具调用、状态管理、RAG、数据入库、异步任务、可观测性、测试和前后端服务化。

> 仅用于研究、模拟决策和工程学习，不构成投资建议，也没有接入真实券商自动下单。

## 一句话理解

用户输入股票代码、分析日期和问题后，系统先按日期过滤可用财报，再从 PostgreSQL + pgvector 检索相关 Chunk；基本面 Agent 结合检索证据组织结论，LangGraph 负责控制多智能体流程，FastAPI 提供接口，React 页面展示证据、报告和任务进度。

## 当前进度

截至当前仓库最新提交，核心链路已经完成并上传：

| 模块 | 状态 | 当前情况 |
| --- | --- | --- |
| LangGraph 多智能体工作流 | 已完成 | 分析师、研究员、交易员、风险角色和组合经理按固定图运行 |
| 局部工具调用循环 | 已完成 | 模型决定调用工具，ToolNode 执行，结果回写原 Agent |
| AgentState 状态管理 | 已完成 | 通过中心状态传递报告、消息、辩论轮次和交易计划 |
| 工具参数校验 | 已完成 | 使用 Pydantic 校验股票代码、日期、指标和财报参数 |
| 财报采集和处理 | 已完成 | 支持 SEC 公开财报发现、下载、哈希校验、清洗和 Chunk 切分 |
| PostgreSQL + pgvector | 已完成 | 保存文档、Chunk、全文索引、Embedding 状态和向量 |
| RAG 检索 | 已完成 | 支持关键词、向量和 Hybrid 检索，并过滤股票与未来日期证据 |
| RAG 评测 | 已完成 | 已保存四种策略的 Recall@5、MRR、引用覆盖率和 P95 报告 |
| 基本面 Agent 接入 RAG | 已完成 | RAG 检索结果通过统一工具返回给基本面 Agent，并带引用和 Trace |
| FastAPI 演示服务 | 已完成第一版 | 提供检索、Agent 报告、覆盖范围和财报入库任务接口 |
| React + TypeScript 前端 | 已完成第一版 | 展示检索证据、评级、报告章节、任务状态和股票覆盖范围 |
| 异步财报入库 | 已完成第一版 | 默认进程线程池，可选 Redis + Celery 执行器 |
| 自动定时发现新财报 | 规划中 | 当前可以手动创建增量任务，定时调度仍是下一阶段 |
| 完整多轮辩论的稳定恢复 | 规划中 | 已有上下文限制和路由保护，完整长任务还需要异步化与 checkpoint 恢复 |

### 已有真实结果

- RAG 评测报告：`docs/R-12-D-evaluation-report.html`。
- 固定样本评测中，向量检索 Recall@5 为 `100.00%`，Hybrid 为 `97.22%`，关键词检索为 `80.56%`。
- 四种策略的未来证据泄露率均为 `0%`。
- 评测记录了 MRR、引用覆盖率和 P95 延迟；关键词检索 P95 为 `6.990 ms`，向量检索 P95 为 `56.580 ms`，Hybrid P95 为 `55.803 ms`。
- 真实 Embedding 工单中，330 个 Chunk 成功生成向量并写入 PostgreSQL，数据库向量维度为 1536。
- 真实基本面 RAG 运行记录在 `docs/R-13-postgres-rag-agent-trace.md`，其中明确区分了检索工具层已验证和完整多轮辩论仍存在的网关超时边界。

这些数字属于当前固定样本和运行环境的实测结果，不代表所有股票、所有模型和所有网络环境都能得到相同结果。

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

## 工单和学习路线

建议按下面顺序阅读，而不是一开始就直接看所有代码：

1. [智能体学习与完善路线](docs/AGENT_LEARNING_ROADMAP.md)：看整体阶段、面试问题和工单依赖。
2. [亲手复现手册](docs/LEARNING_RUNBOOK.md)：按命令验证基础工作流和工具调用。
3. [架构选型记录](docs/ADR-001-architecture-decision.md)：理解为什么使用 LangGraph 固定工作流。
4. [RAG 工单参考](skills/tradingagents-agent-growth/references/rag-workorders.md)：看文档入库、检索、Agent 接入和服务化顺序。
5. `docs/R-01` 到 `docs/R-15`：按编号阅读每张工单的实现、结果、限制和面试回答。
6. [RAG 评测 HTML 报告](docs/R-12-D-evaluation-report.html)：查看真实策略对比。
7. [PostgreSQL RAG Agent Trace](docs/R-13-postgres-rag-agent-trace.md)：查看真实工具层和端到端运行边界。

每张工单都尽量保留四类证据：代码、测试、设计说明和面试版总结。项目中“已完成”表示代码、文档或对应验收已经存在；“第一版”表示可以演示，但还没有包装成完整生产系统；“规划中”表示还没有把它说成现有能力。

## 当前限制和下一步

当前最需要继续完善的是：

- 把长时间的完整多智能体运行放入可靠的异步任务和节点级 checkpoint/resume，降低单次网关超时的影响。
- 增加 SEC 定时发现和增量同步，让新财报自动进入下载、解析、Chunk、Embedding 和入库链路。
- 建立股票覆盖、最新可用日期、向量成功率和失败原因的持续指标。
- 补充在线 SEC 兜底与本地 PostgreSQL 检索的延迟、成功率和稳定性对比。
- 在稳定模型网关上补齐完整回答级 Token 和成本观测，不能用 Embedding 延迟代替 LLM 成本。
- 继续补充鉴权、限流、报告持久化和部署回滚能力。

## 关于仓库内容和敏感配置

当前仓库已经同步代码、工单、Skill、上下文资料、真实财报样本、Chunk、评测结果、运行报告和前端构建产物。按本项目的私有仓库使用约定，当前提交也保留了本地 `.env` 配置快照；如果仓库改为公开，或密钥曾经被其他人看到，应立即撤销并重新生成对应密钥。

本地 `.venv/`、`frontend/node_modules/`、`__pycache__/`、测试缓存等仍然不上传，因为它们是机器相关的依赖和临时文件，不是项目源代码或学习资料。

## 上游项目与许可证

本项目基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 继续学习和改造，仓库保留上游的许可证和引用信息。上游项目的原始说明、架构图片和许可证请参阅 [CHANGELOG.md](CHANGELOG.md)、[LICENSE](LICENSE) 以及仓库中的 `assets/`。
