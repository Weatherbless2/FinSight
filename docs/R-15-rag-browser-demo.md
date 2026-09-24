# R-15：FastAPI RAG 浏览器演示

## 启动

```bash
cd ~/projects/TradingAgents
source .venv/bin/activate
TRADINGAGENTS_ENABLE_POSTGRES_RAG=true \
uvicorn scripts.run_rag_demo:app --host 127.0.0.1 --port 8000
```

浏览器打开：`http://127.0.0.1:8000`

接口文档：`http://127.0.0.1:8000/docs`

健康检查：`http://127.0.0.1:8000/health`

## 页面功能

- 输入股票代码、分析日期和研究问题。
- 选择关键词、向量或 Hybrid 检索。
- 展示真实命中的 Chunk、章节、文档类型、来源 URL、相似度和检索耗时。
- 显示 `available_at <= as_of` 日期边界是否通过。
- 点击“生成基本面 Agent 报告”时，调用已有的基本面专项 LangGraph 流程和 `gpt-5.5`，不是前端伪造答案。
- 报告按评级、摘要、财务信息、风险、展望和详情分区展示；原始 Markdown 只在底部折叠查看。
- 页面顶部显示 PostgreSQL 当前已有的股票覆盖范围、文档数和 Chunk 数。
- `TRADINGAGENTS_ENABLE_ONLINE_FALLBACK=true` 时，本地无命中才允许访问 SEC 官方资料；在线结果会标记为未持久化。
- `POST /api/ingestion-jobs` 可以为新股票创建异步 SEC 增量入库任务，使用 `GET /api/ingestion-jobs/{job_id}` 查询状态。

## 当前结果

页面复用真实 TSLA PostgreSQL 数据：9 份文档、1432 个 Chunk、1432 个 1536 维向量。检索接口只读数据库，不修改 RAG 数据。

启用 SEC 在线兜底：

```bash
TRADINGAGENTS_ENABLE_POSTGRES_RAG=true \
TRADINGAGENTS_ENABLE_ONLINE_FALLBACK=true \
uvicorn scripts.run_rag_demo:app --host 127.0.0.1 --port 8000
```

创建一只新股票的异步入库任务：

```bash
curl -X POST http://127.0.0.1:8000/api/ingestion-jobs \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"AMZN","as_of":"2025-03-01","limit_per_form":1}'
```

也可以使用脚本入口：

```bash
TRADINGAGENTS_ENABLE_POSTGRES_RAG=true \
python scripts/run_rag_demo.py --port 8000
```

## 当前边界

- 当前异步任务默认使用 FastAPI 进程内线程池；已加入可选的 Redis/Celery 执行器。设置 `TRADINGAGENTS_TASK_EXECUTOR=celery` 后，API 只投递任务，需要另起 Celery Worker。
- 在线兜底只在内存中检索当前请求；持久化由异步任务完成，不把长时间下载放进 Agent 请求。
- React + TypeScript + Vite 前端源码已放在 `frontend/`，通过 Vite 代理访问 FastAPI；当前使用兼容 Node 18 的 Vite 5，生产构建和开发服务已经验收。FastAPI 内置页面仍可作为后端直连演示入口。

启用 Redis/Celery：

```bash
docker compose --profile rag up -d redis
source .venv/bin/activate
pip install -r requirements.txt
TRADINGAGENTS_TASK_EXECUTOR=celery celery -A tradingagents.tasks.ingestion_tasks.celery_app worker --loglevel=INFO
```

## 面试讲法

我补了一个 FastAPI 投研工作台：本地知识库优先返回 PostgreSQL/pgvector 证据；没有本地材料时，在显式开关下通过 SEC 官方来源在线兜底，并把新材料交给异步入库任务。Agent 报告使用结构化契约返回评级、摘要、风险、展望和原始结果，页面同时展示来源、日期边界、任务状态和运行指标。这样既能现场证明 Agent 基于证据分析，也能说明在线采集不会阻塞主请求。
