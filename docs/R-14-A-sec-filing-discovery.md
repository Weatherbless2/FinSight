# R-14-A：SEC 财报自动发现

## 目标

输入股票代码和分析日期，使用 SEC 官方元数据接口发现已经公开的 10-K、10-Q
和 8-K 文档，输出后续下载任务可直接消费的候选列表。本工单不下载正文、不解析
HTML、不切分 Chunk，也不生成 Embedding。

## 实现链路

```text
ticker
  -> SEC company_tickers.json
  -> CIK
  -> SEC submissions/CIKxxxxxxxxxx.json
  -> 表单和日期过滤
  -> accession + primaryDocument 拼接归档 URL
  -> R-14-B 下载清单
```

## 关键规则

- 支持 `10-K`、`10-K/A`、`10-Q`、`10-Q/A`、`8-K`、`8-K/A`。
- 使用 `filingDate` 作为 `available_at`，只保留 `filingDate <= as_of` 的文档。
- 10-K 映射为 `annual_report`，10-Q 映射为 `quarterly_report`，8-K 映射为 `announcement`。
- 每个候选保存 CIK、表单、申报日期、报告期、accession number、主文档和 SEC URL。
- 所有请求使用统一 `User-Agent` 和超时；网络或返回格式异常转换成 `SECDiscoveryError`。
- 只返回元数据候选，不在用户 Agent 请求期间执行下载和向量化。

## 使用命令

```bash
export SEC_USER_AGENT='TradeAgent/0.3 (your-email@example.com)'
python scripts/discover_sec_filings.py \
  --ticker TSLA \
  --as-of 2025-03-01 \
  --limit-per-form 3 \
  --output data/sec_discovery/tsla-2025-03-01.json
```

## 面试讲法

我把财报发现拆成独立的数据准备模块。模块先通过 SEC 官方 ticker 映射获取 CIK，
再读取 submissions 记录，按表单类型和分析日期过滤，并根据 accession number 和
primary document 生成稳定的原文地址。Agent 运行时只查询已经准备好的数据库，避免
把外部网站限流、下载和解析耗时放进用户请求链路。后续下载、解析、切分和向量化由
R-14-B 和 R-14-C 继续处理。
