# R-04：公开财报与公告导入

## 问题

公开财报和公告如何进入 RAG，并且在下载失败、文件过大或来源内容变化时仍然保留可审计记录？

## 做了什么

- 新增 \`tradingagents.rag.ingestion.fetch_document()\`，校验 HTTP(S)、设置 User-Agent、请求超时和最大文件大小。
- 新增 \`FetchedDocument\`，以原始 \`bytes\` 保存内容并计算 SHA-256。
- 新增 \`build_document_metadata()\`，把实际下载内容哈希写入 R-01 契约。
- 新增 \`store_raw_document()\`，保存原文和成功 JSON 清单。
- 新增 \`write_failed_manifest()\`，下载失败时保存来源、错误类型和错误信息。
- 新增 \`scripts/ingest_public_document.py\`，支持手动导入单个公开文档。

## 目的

先建立可追溯的原始数据入口，再进入 R-05 解析和清洗。原始文件使用 bytes 保存，避免 PDF 或非 UTF-8 文本被错误转码；内容哈希用于后续 PostgreSQL 去重和文档版本识别。

## VS Code WSL 项目修改

- \`tradingagents/rag/ingestion.py\`：下载、大小限制、哈希、原文落盘和失败清单。
- \`tradingagents/rag/__init__.py\`：导出导入接口。
- \`scripts/ingest_public_document.py\`：命令行导入入口。
- \`tests/test_rag_ingestion.py\`：3 个最小冒烟测试，全部使用 Mock，不访问真实网络。
- \`docs/R-04-public-document-ingestion.md\`：记录使用方式和边界。

## 导入命令

先进入项目：

```bash
cd /root/projects/TradingAgents
```

导入一个公开 HTML 或 PDF：

```bash
.venv/bin/python scripts/ingest_public_document.py \
  --url "https://example.com/report.html" \
  --document-id "aapl-2025q1-release" \
  --ticker "AAPL" \
  --document-type "earnings_release" \
  --title "AAPL 2025 Q1 earnings release" \
  --published-at "2025-01-31" \
  --available-at "2025-01-31" \
  --output-dir "data/raw_documents"
```

成功后会生成：

```text
data/raw_documents/aapl-2025q1-release-<sha12>.raw
data/raw_documents/aapl-2025q1-release-<sha12>.json
```

失败时只生成 status=failed 的 JSON 清单，文件名使用哈希，不会把非法输入拼接进路径，也不会进入后续解析流程。

## 测试与结果

```bash
pytest -q tests/test_rag_ingestion.py
```

实际结果：

```text
3 passed
```

测试覆盖成功下载、超大文件拦截和失败清单落盘；没有测量真实网络延迟，也没有连接 PostgreSQL。

## 设计取舍

本工单先支持单文档手动导入，不提前实现批量调度、重试队列或数据库写入。真实 SEC 导入时应提供符合 SEC 要求的识别性 User-Agent；当前命令提供 \`--user-agent\` 参数。网络重试和限流属于后续可靠性工单，不在 R-04 扩大范围。

## 30 秒面试答案

我先把公开财报和公告做成可审计的原始数据入口：下载时校验 URL、超时和文件大小，原文按 bytes 保存并计算 SHA-256，同时写入来源、内容类型、抓取时间和状态清单。失败不会静默丢失，而是生成失败记录。这样后续解析、切分和入库都有稳定的原始依据。

## 当前结果与下一步

下载器、命令行入口和失败记录已完成；测试 3 个通过。当前还没有真实文档进入仓库，也没有解析 HTML/PDF。下一步是 R-05：解析和清洗已导入的 HTML 文档，保留章节、表格和原文位置。
