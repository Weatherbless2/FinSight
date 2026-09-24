# R-14-C：SEC HTML 解析、清洗与 Chunk 构建

## 工单目标

把 R-14-B 下载的 SEC HTML 原文转换为后续 Embedding 和 PostgreSQL 入库可以使用的 Chunk JSONL。本工单复用 R-05 的 HTML 解析器和 R-06 的 Chunk 切分器，不处理 PDF/OCR，也不生成 Embedding。

## 实现步骤

1. 读取成功下载清单，校验元数据，并根据清单旁边的 `.raw` 文件读取原始 bytes。
2. 重新计算 SHA-256，与成功清单中的 `source_hash` 对比；哈希不一致时停止当前文档，防止原文被替换后继续处理。
3. 使用 `parse_html_document()` 删除脚本、导航、页眉页脚和重复免责声明，保留标题、段落、列表和表格。
4. 针对 SEC 常见的 `div/span` 页面结构，识别叶子 `div` 正文和 `PART/ITEM` 章节标题，避免只抓到表格而漏掉管理层讨论和风险因素。
5. 过滤 `display:none` 的 XBRL 辅助标识，避免把隐藏元数据误当成业务证据。
6. 使用 `chunk_document()` 按章节和段落边界切分普通正文；目标约 450 个估算 Token，硬上限 700。
7. 表格独立切分，并保留表格标题和表头，防止金额、单位和期间脱离语义；表头异常过长时也按硬上限兜底。
8. 输出每份文档的 `.chunks.jsonl`，每行同时保存父文档元数据、Chunk 元数据、正文和字符位置。
9. 新增 `--ticker` 参数，支持只处理某一家公司的成功清单，避免多公司批处理时混入无关文档。

## 使用命令

```bash
cd ~/projects/TradingAgents
source .venv/bin/activate

python scripts/build_real_chunks.py \
  --input-dir data/raw_documents \
  --output-dir data/processed_documents/sec-tsla \
  --ticker TSLA \
  --target-tokens 450 \
  --max-tokens 700
```

## 业务目的

财报原文不能直接整篇送给 Agent。解析器先去掉网页噪声，切分器再把长文档拆成带章节和位置的证据片段。这样后续检索可以返回“哪一份财报、哪个章节、哪一段原文”，而不是只返回一大段无法引用的文本。

## 实际验证结果

使用 R-14-B 真实下载的 TSLA 财报执行后，处理了 9 份 SEC HTML，生成 9 份 Chunk JSONL。实测生成 1432 个 Chunk，识别 716 个章节块和 636 个表格块；最大 Chunk 为 696 个估算 Token，没有超过 700 的硬上限；最小 Chunk 为 2 个估算 Token，低于 5 Token 的 Chunk 为 22 个，主要是合法的 `None.` 等短披露。构建摘要写入输出目录的 `build-summary.json`，其中记录每份文档的原始字节数、解析块数量、表格数量、Chunk 数量和估算 Token 范围。

这次真实运行还发现并修复了两个 SEC 特有问题：`div/span` 正文结构会导致管理层讨论漏抓，`display:none` 的 XBRL 标识会造成无意义长 Chunk。修复后章节和正文可被解析，隐藏 XBRL 和独立页码不会进入 Chunk；复杂表头仍会遵守硬上限。

## 当前边界

当前已支持真实 SEC HTML；PDF、扫描件 OCR、复杂跨页表格还没有接入。当前 `token_count` 是确定性估算值，不能直接当作某个 Embedding 模型的精确 Token 计费值。下一步是把这些真实 Chunk 写入 PostgreSQL，并生成 Embedding。

## 面试讲法

我把文档处理拆成“原文校验、结构化解析、语义切分”三步。先用 SHA-256 确认原文没有被替换，再过滤 HTML 噪声并保留章节和表格，最后按段落边界生成 450 Token 左右、700 Token 硬上限的 Chunk。表格会独立保存并重复表头，Chunk ID 由文档 ID、顺序和内容哈希生成，后续可以稳定入库、检索和引用。
