# R-12-A：真实公开财报导入与 Chunk 构建

## 问题

R-12 的评测器已经完成，但没有真实财报 Chunk。如何从公开 SEC 文档开始，实际下载、校验哈希、解析 HTML，并按 R-06 规则生成可供 Embedding 和 PostgreSQL 使用的 Chunk？

## 本次真实数据

- AAPL：2025-01-31 提交的 2025 Q1 10-Q。
- MSFT：2025-07-30 提交的 FY2025 10-K。
- NVDA：2025-02-26 提交的 FY2025 10-K。

三份文档均来自 SEC Archives，导入时保存了 URL、公开日期、原始字节和 SHA-256。

## 实现步骤

1. 使用 `scripts/ingest_public_document.py` 调用 SEC 公开 URL。
2. 在 `data/raw_documents` 保存原始 HTML 和成功清单。
3. 使用 `scripts/build_real_chunks.py` 读取清单和原始 HTML。
4. 调用 `parse_html_document()` 删除脚本、导航和重复噪声，同时保留标题、段落和表格。
5. 调用 `chunk_document()` 按章节/段落切分，普通 Chunk 目标 450 tokens、硬上限 700，表格独立处理。
6. 将每个 Chunk 写入 `data/processed_documents/*.chunks.jsonl`，同时生成 `build-summary.json`。

## 实际导入结果

原始文件已经成功下载：

```text
AAPL：716K
MSFT：7.8M
NVDA：2.0M
总计约 11M
```

实际构建结果：

| 股票 | 原始字节 | 解析块 | 表格块 | Chunk | 最大估算 Token | 平均估算 Token |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 732,953 | 29 | 29 | 29 | 473 | 153.17 |
| MSFT | 8,158,431 | 1,134 | 85 | 231 | 699 | 239.90 |
| NVDA | 2,067,884 | 67 | 67 | 70 | 694 | 167.16 |
| 合计 | 10,959,268 | 1,230 | 219 | 330 | - | - |

MSFT 其中 9 个 Chunk 的估算 Token 不超过 5，内容主要是目录页码或目录标题；这说明真实 SEC HTML 还需要下一步目录噪声清理，当前不能把所有 Chunk 都视为高质量业务证据。完整摘要以 `data/processed_documents/build-summary.json` 为准。

## 运行命令

```bash
cd /root/projects/TradingAgents

.venv/bin/python scripts/build_real_chunks.py \
  --input-dir data/raw_documents \
  --output-dir data/processed_documents
```

查看摘要：

```bash
cat data/processed_documents/build-summary.json
```

## 当前限制

- 当前只处理 HTML，PDF/OCR 尚未接入。
- Chunk 位置是清洗后文本的字符位置，尚未保存 PDF 页码。
- 真实 Chunk 已生成，但还没有真实 Embedding、PostgreSQL 入库和四策略检索对比。
- SEC 文档属于公开来源，仍需保留来源 URL 和哈希，不能把原文发布到不受控的公共位置。

## 下一步

R-12-B：启动 PostgreSQL + pgvector，建立真实文档和 Chunk 入库适配；随后接入 R-12-C 的真实 Embedding。
