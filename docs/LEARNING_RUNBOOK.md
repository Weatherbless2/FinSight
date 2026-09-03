# TradeAgent 亲手复现与面试学习手册

## 这份手册解决什么问题

路线中的功能虽然已经落到代码和测试里，但只有亲手运行、观察结果并讲清设计取舍，才能真正成为面试中的项目经验。本手册按 A-01～A-05、B-01 的顺序给出命令、预期结果和总结话术。

项目目录统一使用：

```bash
cd /root/projects/TradingAgents
```

所有命令都在 VS Code 的 WSL 终端中执行。

## 0. 环境确认

```bash
pwd
.venv/bin/python --version
.venv/bin/python -c "import tradingagents, langgraph, pydantic; print('环境正常')"
```

怎么看：

- `pwd` 应输出 `/root/projects/TradingAgents`。
- Python 命令最后输出 `环境正常`，表示核心依赖可以导入。
- 如果 `.venv/bin/python` 不存在，在全新克隆中执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

`.env` 只在本地保存密钥，不提交 Git。

## A-01：看懂整体工作流和局部工具循环

面试问题：为什么采用固定工作流加局部“思考—行动—观察”循环？

```bash
grep -nE "StateGraph|add_node|add_edge|add_conditional_edges|ToolNode" \
  tradingagents/graph/setup.py \
  tradingagents/graph/trading_graph.py \
  tradingagents/graph/conditional_logic.py
```

重点观察：

1. `StateGraph(AgentState)` 创建全局固定工作流。
2. `add_node` 注册分析师、工具、研究员、交易员和风险角色。
3. `add_conditional_edges` 根据 `tool_calls` 或辩论轮数选择下一节点。
4. `workflow.add_edge(current_tools, current_analyst)` 让工具执行后回到原分析师。

总结话术：

> 整体流程由 LangGraph 固定节点顺序，保证金融分析可控、可回放；分析师内部允许模型按需选择白名单工具，保留局部灵活性，因此不是完全自主 Agent。

## A-02：理解 AgentState 如何传递数据

```bash
.venv/bin/python -c 'from tradingagents.agents.utils.agent_states import AgentState; fields=AgentState.__annotations__; print(f"AgentState 字段数: {len(fields)}"); print("\n".join(fields))'
```

当前预期：

```text
AgentState 字段数: 16
messages
company_of_interest
asset_type
instrument_context
trade_date
sender
market_report
sentiment_report
news_report
fundamentals_report
investment_debate_state
investment_plan
trader_investment_plan
risk_debate_state
final_trade_decision
past_context
```

怎么看：

- `messages` 保存当前模型和工具交互，是短期上下文。
- 四个 `*_report` 是分析师交给下游的结构化阶段结果。
- 两个 `*_debate_state` 保存研究辩论和风险辩论的轮数、历史与发言者。
- `past_context` 是决策记忆注入，不等于 SQLite 检查点。

总结话术：

> 多个 Agent 不直接互相调用，而是通过中心化 AgentState 交接消息、报告和辩论状态，字段边界清晰，也便于检查点恢复和测试。

## A-03：验证工具调用为什么会回到分析师

```bash
.venv/bin/python -m pytest -q tests/test_agent_tool_loop.py
```

当前预期：

```text
1 passed
```

测试中的关键断言：

```python
assert visited_nodes == ["agent", "tools", "agent"]  # 实际访问顺序
assert fake_model.call_count == 2                      # 调工具前后各思考一次
assert "最终报告" in result["report"]                 # 第二次返回最终报告
```

总结话术：

> `bind_tools` 只让模型生成工具调用请求，真正执行由 `ToolNode` 完成；工具结果写回 messages 后，条件边把控制权交还原分析师，直到模型不再产生 tool_calls。

## A-04：验证循环上限和异常路由保护

```bash
.venv/bin/python -m pytest -q tests/test_router_guards.py
```

当前预期：

```text
8 passed
```

怎么看：

- 空 `messages` 会明确抛错，不会静默走错节点。
- `recursion_limit` 会写入图执行配置。
- 多空研究达到 `2 × max_debate_rounds` 后进入研究经理。
- 三方风险辩论达到 `3 × max_risk_discuss_rounds` 后进入组合经理。
- 路由结果只能落到图中已经声明的目标。

总结话术：

> 我用图级递归上限和业务轮数上限做双重保护，并对空状态和路由目标增加回归测试，避免 Agent 死循环或运行中途进入不存在的节点。

## A-05：理解架构选型

```bash
sed -n '1,260p' docs/ADR-001-architecture-decision.md
```

阅读时重点回答：

- 为什么 LangChain 只负责模型和工具协议？
- 为什么 LangGraph 负责状态、条件边和恢复？
- 为什么不用一个大提示词、纯自主 Agent 或 Dify 作为核心运行时？

当前结构实测记录：默认图 20 个节点、9 条条件路由、26 个条件目标、13 个默认工具。它们是架构规模指标，不代表一次运行一定访问全部节点。

总结话术：

> 我们选择 LangChain 统一模型和工具协议，选择 LangGraph 管理有状态工作流。固定主链保证可控和可审计，局部工具循环保留灵活性，代价是新增角色时需要显式修改图结构。

## B-01：验证非法工具参数不会进入供应商

```bash
.venv/bin/python -m pytest -q tests/test_tool_input_validation.py
```

当前预期：

```text
24 passed
```

其中包含 21 条非法样本和 3 条合法回归。每条非法样本都断言：

```python
assert error.value.code == "INVALID_INPUT"  # 对外错误码稳定
vendor.assert_not_called()                   # 非法请求没有访问数据供应商
```

覆盖股票代码、危险路径、日期格式、倒序日期、指标白名单、回看天数、财报频率和数量上限。

总结话术：

> 13 个 LLM-facing 工具都先经过统一 Pydantic 校验。21 条非法参数样本实现 100% 入口拦截，供应商调用为 0，合法请求继续沿用原供应商路由。

## 一次验证当前全部学习工单

```bash
/usr/bin/time -f "ELAPSED_SEC=%e" \
  .venv/bin/python -m pytest -q \
  tests/test_agent_tool_loop.py \
  tests/test_router_guards.py \
  tests/test_tool_input_validation.py
```

2026-09-03 实测：

```text
33 passed in 1.18s
ELAPSED_SEC=2.20
```

机器负载会影响耗时，验收重点是 `33 passed` 和 `0 failed`。

## 静态检查与全量回归

```bash
.venv/bin/ruff check tradingagents tests
/usr/bin/time -f "ELAPSED_SEC=%e" .venv/bin/python -m pytest -q
```

当前全量基线：

```text
609 passed
2 skipped
18 warnings
69 subtests passed
ELAPSED_SEC=258.77
```

怎么看：

- `failed` 必须为 0。
- 两个跳过项来自未安装的可选 `langchain_aws` 和未配置的 DeepSeek 实时密钥。
- `warnings` 是未知模型目录提醒，不等于测试失败。
- 耗时是本机回归数据，不是线上接口性能承诺。

## 本地运行项目

```bash
source .venv/bin/activate
python -m cli.main
```

在交互界面选择股票、日期、模型供应商、分析师和辩论深度。运行时重点观察分析师报告、工具调用次数、令牌统计、风险辩论和最终评级。真实模型和数据接口会产生费用或限流，先从较少分析师和较浅辩论轮数开始。

## GitHub 同步检查

```bash
git status --short
git remote -v
git ls-files .env
git diff --check
git log --oneline --decorate -5
```

判断方式：

- `git ls-files .env` 应该没有输出，表示真实密钥没有进入 Git。
- `origin` 应指向 `git@github.com:Weatherbless2/TradeAgent.git`。
- `upstream` 应指向原始 TradingAgents 仓库。
- `git diff --check` 没有输出表示没有空白格式错误。

后续自己提交时使用：

```bash
git add <本次工单涉及的文件>
git diff --cached --stat
git diff --cached --check
git commit -m "feat: 完成 B-02 统一工具结果契约"
git push origin main
```

先检查暂存区再提交，不使用 `git add .` 去盲目收集文件，也不使用 `git push --force`。

## 当前完整面试总结

> 我基于 TradingAgents 搭建了一套面试驱动的 Agent 工程化学习路线。项目宏观上使用 LangGraph 固定工作流，微观上让分析师通过 LangChain 和 ToolNode 进行有限工具循环，并通过中心化 AgentState 交接报告和辩论状态。我补充了工具循环、空状态、路由边界和循环上限测试，又为 13 个工具增加了统一 Pydantic 输入校验。当前 21 条非法参数样本的拦截率为 100%，供应商调用为 0；全量回归为 609 passed。项目仍是金融研究和模拟决策系统，下一步是统一工具失败、降级和重试信息的结果契约。
