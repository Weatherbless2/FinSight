# R-14-B：SEC 财报批量下载与原文落盘

## 工单目标

把 R-14-A 生成的 SEC 候选清单消费成可供后续解析的原始文档。这个工单只负责下载、校验、哈希和落盘，不负责 HTML 清洗、Chunk 切分、Embedding 或 PostgreSQL 入库。

## 实现步骤

1. 读取 R-14-A 的 JSON，并用 `SECFilingCandidate` 逐条校验字段。
2. 用 `available_at <= as_of` 和 `filing_date <= as_of` 做第二道时间边界检查，避免未来材料进入历史分析。
3. 扫描输出目录中的成功清单；同一 `document_id` 已有成功版本时直接跳过，保证重复执行幂等。
4. 对新文档调用已有 `fetch_document()`，沿用 SEC `User-Agent`、超时和最大文件大小限制。
5. 将 SEC 字段映射到统一的 `FinancialDocumentMetadata`：申报日作为 `published_at` 和 `available_at`，报告期结束日作为 `period_end`。
6. 使用实际下载 bytes 计算 SHA-256，按 `{document_id}-{sha12}.raw` 保存原文，旁边保存成功 JSON 清单。
7. 单条下载失败时写入 `failed-<hash>.json`，继续处理后续文档；最终汇总保存每一条的状态。
8. 同一文档存在多个成功哈希时报告冲突，不静默覆盖，避免来源内容变化被隐藏。

## 使用命令

```bash
cd ~/projects/TradingAgents
source .venv/bin/activate

SEC_USER_AGENT='TradeAgent/0.3 (local development; contact: your-email@example.com)' \
python scripts/ingest_sec_filings.py \
  --input reports/r14/tsla-2025-03-01-discovery.json \
  --output-dir data/raw_documents \
  --summary reports/r14/tsla-2025-03-01-ingestion.json
```

退出码：全部成功或跳过为 `0`；存在失败项为 `2`；输入参数或清单无效为命令错误。

## 输出如何理解

- `stored`：本次实际下载并保存了原文。
- `skipped_existing`：已有相同文档的成功清单，本次没有重复请求。
- `filtered_future`：文档日期晚于分析日，没有进入下载。
- `failed`：下载或落盘失败，失败原因写在失败清单中，可单独重试。

## 业务目的

把“网上发现财报”变成可审计的数据准备流程。Agent 在线分析时只需要读取已经准备好的文档和向量，不必在用户请求期间访问 SEC、等待下载或承担外部接口波动；同时哈希和失败清单让文档版本变化、重复执行和异常重试都有记录。

## 当前边界

本工单不声称已经完成 PDF/HTML 解析、语义切分、Embedding 和 PostgreSQL 入库。后续仍需依次执行 R-05、R-06、R-07 和 R-03/R-12-B 的相关流程。

## 实际验证结果

使用 TSLA、分析日期 `2025-03-01` 的 R-14-A 清单进行真实 SEC 网络下载：

```text
候选 9 条
成功保存 9 条
已存在跳过 0 条
未来文档过滤 0 条
下载失败 0 条
真实命令耗时约 9.2 秒
```

原文和成功清单实际写入 `data/raw_documents/`，原文大小约 28 KB～2.67 MB，具体哈希和文件路径记录在 `reports/r14/tsla-2025-03-01-ingestion.json`。

随后使用同一命令再次执行：

```text
候选 9 条
成功保存 0 条
已存在跳过 9 条
未来文档过滤 0 条
下载失败 0 条
```

这证明重复执行不会重复下载。全量回归结果为 `691 passed, 2 skipped, 18 warnings, 69 subtests passed`，耗时约 `252.57s`；其中跳过项是未安装可选 Bedrock 依赖和未配置 DeepSeek 实时密钥，不是 R-14-B 失败。

## 面试讲法

面试官问“新公司财报怎么进入 Agent”时，可以回答：我先通过 SEC 官方接口发现候选，再由批处理下载器按分析日期过滤，使用统一 User-Agent 请求原文，计算 SHA-256 并保存原文和元数据清单。任务具备幂等性，已有文档跳过；单条失败留下失败记录并继续处理。下载后的原文再进入解析、Chunk、向量化和 PostgreSQL 检索链路，在线 Agent 不直接承担外部采集风险。
