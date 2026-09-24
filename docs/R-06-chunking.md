# R-06：按章节和段落切分 Chunk

## 问题

财报文本应该怎样切 Chunk，才能既保留金融语义，又控制上下文长度，并让表格和引用位置可追溯？

## 做了什么

- 新增 tradingagents.rag.chunking.chunk_document()。
- 普通正文按章节、段落边界聚合，目标约 450 个估算 token，硬上限 700。
- 超长段落优先按句子边界切分，再按空格或字符边界兜底。
- 表格单独成 Chunk，不和普通段落混合；表格过长时重复表格标题和表头。
- 使用确定性 token 估算，不新增 tokenizer 依赖。
- Chunk ID 使用文档 ID、顺序号和内容哈希生成，内容不变时 ID 稳定。
- 通过 char_start/char_end 保存清洗文本中的引用区间。

## 目的

为 R-07 向量和全文索引提供稳定片段。Chunk 太大容易造成上下文浪费，太小会丢失财务语义；表格如果没有表头和单位，数字会失去含义。

## VS Code WSL 项目修改

- tradingagents/rag/chunking.py：切分、长段落拆分、表格拆分、Chunk ID 和位置计算；关键逻辑带中文注释。
- tests/test_rag_chunking.py：3 个最小测试，覆盖章节聚合、硬上限和表格表头重复。
- docs/R-06-chunking.md：记录规则、命令和限制。

## 测试与结果

    .venv/bin/pytest -q tests/test_rag_chunking.py

当前 token_count 是确定性估算值，不代表具体 Embedding 模型的真实 tokenizer 统计；R-07 选择模型后再对齐。

## 设计取舍

当前采用普通正文目标 450、硬上限 700、表格独立和表头重复。没有强行固定字符数，因为财报中英文、表格和数字的 token 密度不同；也没有引入 tiktoken，避免在 Embedding 模型确定前增加依赖。

## 30 秒面试答案

我没有按固定字符数粗暴切分，而是优先遵守章节和段落边界。普通 Chunk 目标约 450 tokens，硬上限 700；长段落按句子边界拆分；表格独立切分并重复标题和表头，避免财务数字失去单位和语义。Chunk ID 基于内容哈希生成，便于后续幂等入库和引用追踪。

## 当前结果与下一步

Chunk 切分逻辑已完成，下一步是 R-07：选择 Embedding Provider，生成向量并和 PostgreSQL 全文索引关联。
