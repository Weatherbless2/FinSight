# TradingAgents 项目基线

这是 2026-09-01 核验过的初始地图。代码发生变化后，使用其中结论前必须重新检查仓库。

## 核心运行链

TradingAgents 是 LangGraph `StateGraph`，不是自由形态的自主系统：

```text
输入股票代码和日期
  -> 分析师序列
  -> 多空研究辩论
  -> 研究经理
  -> 交易员
  -> 三角色风险辩论
  -> 组合经理
  -> 报告、记忆日志、可选检查点
```

分析师是局部“思考—行动—观察”式循环：大模型调用已绑定工具，`ToolNode` 执行，条件边把控制权返回给同一分析师，直到其输出报告。工作流和辩论长度由条件路由与递归上限共同限制。

| 关注点 | 已核验位置 |
| --- | --- |
| 图节点和边 | `tradingagents/graph/setup.py` |
| 条件循环 | `tradingagents/graph/conditional_logic.py` |
| 初始图状态 | `tradingagents/graph/propagation.py` |
| 编排和 `ToolNode` | `tradingagents/graph/trading_graph.py` |
| 智能体间状态字段 | `tradingagents/agents/utils/agent_states.py` |
| 分析师提示词和绑定工具 | `tradingagents/agents/analysts/` |
| 结构化数据定义与降级 | `tradingagents/agents/schemas.py`、`agents/utils/structured.py` |
| 数据供应商路由和失败处理 | `tradingagents/dataflows/interface.py` |
| 缓存、重试、过期数据和日期保护 | `tradingagents/dataflows/stockstats_utils.py` |
| 追加式决策记忆 | `tradingagents/agents/utils/memory.py` |
| SQLite 恢复检查点 | `tradingagents/graph/checkpointer.py` |
| 基础大模型/工具/令牌计数 | `cli/stats_handler.py` |
| 分析师耗时汇总 | `tradingagents/graph/analyst_execution.py` |
| 工程回归测试 | `tests/` 与 `.github/workflows/ci.yml` |

## 已实现能力

- 多大模型供应商抽象和按供应商配置。
- 通过 LangChain 绑定工具、LangGraph `ToolNode` 执行的分析师工具调用。
- 中心化 `AgentState`、有限的研究/风险辩论循环和图递归上限。
- 研究经理、交易员、组合经理的 Pydantic 结构化输出及自由文本降级。
- 市场数据路由、缓存、部分重试/降级、明确的无数据处理、代码标准化、过期数据防护和减少未来数据泄漏的日期过滤。
- Markdown 决策记忆和可选 SQLite 检查点恢复。
- 命令行中的大模型/工具调用次数与输入/输出令牌统计。
- 按配置顺序执行的分析师耗时统计。
- Docker、持续集成流程和较充分的确定性单元测试。

## 有意保留的限制与缺口

- 没有通用上下文窗口预算、滑动窗口或辩论摘要。
- 没有向量库记忆、向量嵌入流程、检索增强生成、重排序或引用校验系统。
- 没有标准化智能体质量评测集、回放执行器或线上 A/B 评测。
- 没有完整的单次运行调用链、持久化节点耗时、成本预算或生产级可观测性栈。
- 没有应用级 FastAPI 服务、持久化的用户/任务/报告模型、事件流进度推送、用户认证或多租户授权。
- 没有真实券商执行实现。在独立纸面交易模块完成加固前，应将项目视为研究与模拟决策输出系统。

## 面试安全表述

应该说“受约束工作流中的局部思考—行动—观察式工具循环”，不要说“完全自主的多智能体系统”。应该说“追加式决策记忆”和“检查点恢复”，不要说“检索增强生成”或“向量记忆”。除非当前仓库能够证明已完成，否则调用链追踪、评测、网页接口、安全和交易执行都应描述为计划中工作。
