# R-13：真实 PostgreSQL RAG 接入基本面 Agent

## 面试官会怎么问

“你的财报 RAG 是不是只停留在离线评测？基本面 Agent 真正调用时，如何保证引用安全，并且怎么知道检索用了什么、花了多久？”

## 本工单做了什么

- 新增 `tradingagents/rag/postgres_agent_search.py`，把 `PostgresRetriever` 封装为 `FinancialSearchService` 可调用的 RAG 函数。
- PostgreSQL 命中先经过 `build_database_evidence_bundle()` 做股票、日期、Chunk、来源和正文校验。
- 返回 `hits`、`evidence` 和 `trace`，全部使用 JSON 可序列化字段。
- Trace 记录 `run_id`、查询指纹、策略、候选预算、命中数、文档数、调用次数、耗时、Embedding 模型和成本可用性。
- `TradingAgentsGraph` 增加显式环境变量开关 `TRADINGAGENTS_ENABLE_POSTGRES_RAG=true`；不开启时保持原有结构化 API 行为。
- 将“未配置 RAG”和“RAG 已配置但连接失败”拆成 `RAG_NOT_CONFIGURED` 与 `RAG_ERROR`。

## 数据链路

```text
基本面 Agent
  -> search_financial_documents Tool
  -> FinancialSearchService
  -> PostgresRagSearchAdapter
  -> PostgreSQL 全文/pgvector 检索
  -> 股票与 available_at 过滤
  -> EvidenceBundle 校验
  -> hits + citations + trace JSON
  -> ToolNode 回写给 Agent
```

## 如何开启

```bash
export TRADINGAGENTS_ENABLE_POSTGRES_RAG=true
export TRADINGAGENTS_RAG_STRATEGY=hybrid
```

当前 Ollama Embedding 使用 `nomic-embed-text`；数据库地址仍从 `TRADINGAGENTS_DATABASE_URL` 或 PostgreSQL 环境变量读取，不在 Agent 节点中硬编码。

## 实测结果

专项测试：`16 passed in 1.32s`；RAG 专项测试：`58 passed in 1.61s`。

真实 Docker PostgreSQL + Ollama 工具层冒烟：

| 股票 | 命中 Chunk | 文档数 | 引用数 | 检索耗时 | 未来证据 |
| --- | ---: | ---: | ---: | ---: | --- |
| NVDA | 5 | 2 | 5 | 155.674 ms | 否 |
| AAPL | 5 | 2 | 5 | 45.542 ms | 否 |
| MSFT | 5 | 2 | 5 | 87.036 ms | 否 |

以上是本次真实冒烟值，不代表稳定 P95；完整延迟和召回对比仍以 R-12-D 报告为准。

## 当前限制

- 当前记录了 `token_usage=null`、`cost_usd=null`，因为 Ollama Embedding 接口不提供统一的计费 usage；不能把检索耗时冒充 LLM 成本。
- 本工单验证到基本面搜索工具层，尚未运行完整的多 Agent + LLM 交易图。
- 若数据库容器未启动，服务会返回可重试的 `RAG_ERROR`，而不是伪装成没有配置。

## 终端观测输出

真实运行观测脚本现在会在每个节点执行前后输出中文业务说明，例如：

```text
[运行开始] ticker=NVDA | trade_date=2025-03-01 | 正在启动 LangGraph 固定工作流
[步骤 01][开始] 市场分析师（Market Analyst） | 分析行情和技术指标，并判断是否需要调用市场工具
[步骤 01][完成] 市场分析师（Market Analyst） | 耗时 14.1s | 当前累计步骤 1
[步骤 02][开始] 市场工具节点（tools_market） | 获取行情、技术指标和经过校验的市场快照
```

外部数据供应商异常会显示为“数据源降级”，并明确说明返回空结果或占位结果，避免误以为整个 Agent 失败。`Ctrl+Z` 会挂起进程；要继续当前运行使用 `fg`，要终止使用 `Ctrl+C`。

如果中转模型返回 `524 Proxy Read Timeout`，观测脚本会输出简短失败原因，不再打印整段 traceback。当前项目和观测脚本统一使用 `gpt-5.5`，并将 `--max-retries` 默认设为 `0`，避免一个超时请求被自动重复等待。

设置 `TRADINGAGENTS_RAG_VERBOSE=true` 后，真实 Agent 调用财报搜索工具时会额外显示 `[RAG开始]` 和 `[RAG完成]`，可直接看到股票、分析日期、检索策略、命中 Chunk、引用数量和耗时。`--analysts fundamentals` 只控制分析师选择，不会截断后续研究员和风险节点。

Agent 接入 RAG 时可以通过 `TRADINGAGENTS_RAG_TOP_K` 控制每次返回的 Chunk 数量。评测仍可使用自己的候选预算；当前网关观测建议先设置为 `2`，避免一次把过多财报正文放进模型上下文。

## 本次基本面专项实测

使用 `gpt-5.5`、`TRADINGAGENTS_RAG_TOP_K=5` 和 NVDA 截至 `2025-03-01` 的风险/展望问题，基本面局部工作流真实完成：

```text
总耗时：171.6119s
步骤：6
LLM 调用：3
RAG 检索：3 次
每次 RAG：5 个 Chunk，均通过 future_safe=True
输入 Token：18227
输出 Token：4509
```

报告中实际引用了 NVDA 年报和业绩公告，并输出了风险、管理层展望和需要跟踪的指标。此前完整图在后续 `Bull Researcher` 节点遇到中转网关 `524`，因此进一步增加了上下文预算控制和关闭可选辩论时的图路由修复。

## 本次 524 排查与修复结果

之前的基线先后出现过两类不同问题：

1. `run_real_rag_eval.py` 连接 `127.0.0.1:55432`，但当前 Docker Compose 实际映射为 `127.0.0.1:5432`；已将默认值改为 `5432`，也支持 `TRADINGAGENTS_DATABASE_URL` 显式覆盖。
2. `http://gptch.cloud/v1` 的聊天请求实测返回 `401 Invalid token`，同一网关使用 `https://gptch.cloud/v1` 的 `gpt-5.5` 请求返回 `200`；项目配置和观测脚本已统一为 HTTPS。这个调整没有切换模型，也没有使用 5.6。
3. RAG ToolNode 原来在 `hits[].content` 和 `evidence.citations[].text_excerpt` 中重复携带正文；现在命中列表只保留元数据，证据引用保留唯一正文，减少回写给下一次模型调用的上下文。
4. 观测模式的 `max_debate_rounds=0`、`max_risk_discuss_rounds=0` 之前仍会各执行一次节点；图路由已修正为真正跳过可选辩论，直接进入研究经理和组合经理。生产配置使用大于 0 的轮数时，原有辩论路径仍保留。

使用 `gpt-5.5`、`TRADINGAGENTS_RAG_TOP_K=2`、四类分析师和本地 fixture 的真实端到端观测结果：

```text
最终评级：Hold
总耗时：496.5757 秒
节点步骤：21
LLM 调用：13
工具节点调用：23
输入 Token：18,767
输出 Token：8,788
RAG 检索：真实 PostgreSQL + pgvector，命中 2 个 Chunk，future_safe=True
```

这证明“关闭可选辩论时的完整投研主链路”已经跑通；它不等同于“开启多轮 Bull/Bear 和三路风险辩论时永不超时”。后者仍受 `gptch.cloud` 单请求 120 秒网关限制影响，需要在稳定模型网关或异步任务恢复机制上继续处理。

## 30 秒面试回答

我把真实 PostgreSQL RAG 封装成基本面 Agent 的统一搜索工具。Agent 发起风险、原因或展望类问题后，服务在数据库侧先按股票和分析日期过滤，再执行 Hybrid 检索；返回给 Agent 的不是向量，而是可读 Chunk 和经过确定性校验的引用。每次检索还记录查询指纹、命中数量、文档数量、调用次数、Embedding 模型和耗时。RAG 默认不强制开启，未配置时继续走原有 API，数据库故障则返回明确的可重试错误。当前 Ollama 没有统一计费 usage，所以成本字段明确为空，避免伪造指标。

## 下一步

R-13 的基本面 RAG 专项和关闭可选辩论时的四分析师端到端验收已完成。下一步是把完整辩论模式改造成异步任务并支持节点级 checkpoint/resume，再用固定样本统计成功率、总耗时和失败恢复率；在此之前，不把多轮辩论模式写成稳定生产能力。如果要写简历中的成本指标，需要使用能稳定返回 usage 的聊天模型执行固定样本并单独统计。
