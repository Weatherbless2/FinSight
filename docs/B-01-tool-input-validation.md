# B-01 工具输入校验工单

## 问题：面试官会怎么问？

模型传入非法股票代码、日期、指标或数量参数时，系统怎么处理？如何保证错误请求不会打到外部数据供应商？

## 已核验基线

此前工具函数直接把 LLM 参数传给 `route_to_vendor` 或市场数据构建器。供应商层虽然有部分错误处理，但入口没有统一的字段、范围和日期区间校验。

## 改造

1. 在 `tradingagents/agents/utils/tool_validation.py` 集中定义 Pydantic 输入模型。
2. 使用 `ConfigDict(extra="forbid")` 拒绝模型偷偷附带的未知字段。
3. 统一校验股票代码、日期格式与日历有效性、开始/结束日期顺序、指标白名单、回看天数、新闻/预测市场数量和财报频率。
4. 使用 `ToolInputError(code="INVALID_INPUT")` 对外暴露稳定错误码，避免把 Pydantic 的内部异常结构直接暴露给调用方。
5. 在 13 个 `@tool` 入口先校验，再调用供应商路由；技术指标的逗号分隔输入先规范化，再逐个调用。

## 关键代码

```python
class ToolInputError(ValueError):
    code = "INVALID_INPUT"


class StockDataInput(_ToolInput):
    symbol: str = Field(min_length=1, max_length=32)
    start_date: str
    end_date: str

    _ticker = field_validator("symbol")(_validate_ticker)
    _dates = field_validator("start_date", "end_date")(_validate_date)

    @model_validator(mode="after")
    def check_date_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self
```

上面先挡住空代码和路径穿越字符串，再检查日期格式、真实日历日期和时间顺序。工具入口统一这样使用：

```python
payload = validate_tool_input(
    StockDataInput,
    symbol=symbol,
    start_date=start_date,
    end_date=end_date,
)
return route_to_vendor(
    "get_stock_data", payload.symbol, payload.start_date, payload.end_date
)
```

`validate_tool_input` 捕获 Pydantic `ValidationError`，转换成带字段位置的 `INVALID_INPUT`；只有校验成功后才会执行 `route_to_vendor`。

## 测试

测试文件：`tests/test_tool_input_validation.py`。

- 21 条非法输入样本：空/危险股票代码、非法和倒序日期、未知指标、非法回看天数、错误财报频率、空宏观指标、超范围数量等。
- 每条样本都替换供应商为 `Mock`，验证抛出 `ToolInputError` 且供应商调用次数为 0。
- 合法回归：多指标输入规范化为 `rsi`、`macd` 后分别调用；财报 `curr_date=None` 仍能兼容；全局新闻默认参数正确传递。

## 测试与结果（2026-09-03，WSL 本地实测）

| 项目 | 实测结果 |
| --- | ---: |
| 静态检查 | `ruff check` 通过 |
| B-01 及相关回归 | 44 passed，1.42 秒 |
| 非法样本 | 21 条 |
| 入口拦截 | 21 条（100%） |
| 非法请求触发供应商 | 0 次 |
| 全量测试 | 609 passed，2 skipped，18 warnings，69 个子测试 |
| 全量耗时 | 258.77 秒（`/usr/bin/time`，测试本身报告 257.07 秒） |
| 相对上一基线 | 通过数 585 → 609（+24）；耗时 254.33 → 258.77 秒（+4.44 秒，约 +1.75%，仅作本地回归参考） |

这些是测试环境中的实测值，不是线上延迟承诺。全量跳过项分别是未安装的 `langchain_aws` 和未配置密钥的 DeepSeek 实时调用。

## 取舍

- 采用入口校验而不是只依赖供应商：能减少无效网络请求，并让错误可预测、可测试。
- 指标使用显式白名单，避免供应商收到拼写错误；未来新增指标需要同时更新白名单和测试。
- 日期仍使用字符串比较，因为格式已严格限定为 `YYYY-MM-DD`；可选财报日期允许 `None`，保持原供应商默认行为。
- B-01 只解决“参数是否合法”，不替代 B-02 的统一成功/失败结果契约，也不替代 B-03 的超时和重试。

## 30 秒面试答案

> 我在所有 LLM-facing 工具入口增加了统一的 Pydantic 输入模型和 `INVALID_INPUT` 错误码。股票代码、日期区间、指标白名单、数量范围和财报频率先在本地校验，失败就结构化返回，绝不进入供应商。21 条非法样本的入口拦截率是 100%，供应商调用为 0；合法请求仍按原有路由执行。这样把“模型可能传错参数”的不确定性隔离在工具边界，后续 B-02 再统一处理供应商失败和可重试性。

## 完整总结

当前已实现 13 个工具的统一输入校验、稳定错误码和非法请求零供应商调用保护，并有 21 条非法样本和合法回归测试作为证据。限制是暂时没有统一的 `success/data/error_code/retryable/source/timestamp` 结果包装，也没有统一超时、指数退避和重复调用指纹；这些分别属于下一张 B-02、B-03、B-04 工单。下一步按路线进入 B-02，定义核心工具与可选工具的结构化失败/降级契约。
