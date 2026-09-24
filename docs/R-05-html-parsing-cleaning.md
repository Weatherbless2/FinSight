# R-05：HTML 文档解析与清洗

## 问题

财报和公告 HTML 中包含导航、脚本、页眉页脚、重复免责声明和表格。如何清理噪声，同时保留章节、段落、表格标题和可回溯位置？

## 做了什么

- 新增 tradingagents.rag.parsing.parse_html_document()。
- 删除 script/style/noscript/nav/header/footer/aside/form/svg 等页面噪声。
- 保留 h1-h6 标题、段落、列表项和表格。
- 表格保留 caption、表头、单位和每一行的列关系。
- 重复长免责声明只保留第一次出现，常见导航和版权文本直接过滤。
- 对乱码替换字符和空文档做确定性拒绝。
- 为 HTML 块保留 html-line:<行号> 位置标识，供后续 Chunk 引用。
- PDF 和二进制内容明确拒绝，后续单独扩展。

## 目的

先把原始 HTML 变成稳定的章节块，下一张 R-06 才能按章节和段落边界切 Chunk。当前不生成向量、不写 PostgreSQL，避免解析、切分和检索耦合。

## VS Code WSL 项目修改

- tradingagents/rag/parsing.py：解析、去噪、表格提取和位置保留；关键分支带中文注释。
- tradingagents/rag/__init__.py：导出解析接口。
- tests/test_rag_parsing.py：3 组最小测试，覆盖主路径、重复免责声明和非 HTML 边界。
- docs/R-05-html-parsing-cleaning.md：记录规则、命令和限制。

## 测试与结果

    .venv/bin/pytest -q tests/test_rag_parsing.py

测试不访问网络、不读取真实财报，只使用固定 HTML 字符串。

## 设计取舍

本工单只支持 HTML。HTML 能稳定保留章节和表格结构；PDF 的页码、扫描件 OCR 和复杂表格需要单独选择解析器，放到后续扩展，避免当前主线引入过多依赖。

## 30 秒面试答案

我先对财报 HTML 做结构化清洗：过滤导航、脚本、页眉页脚和重复免责声明，同时保留章节标题、段落、列表和带表头的表格，并记录 HTML 行位置。解析失败或格式不是 HTML 时直接拒绝，不把脏内容送进向量库；后续再按这些章节块进行 Chunk 切分。

## 当前结果与下一步

HTML 解析和清洗已完成，PDF 暂不支持。下一步是 R-06：按章节和段落边界切分 350～550 tokens 的 Chunk，并保留 60～80 tokens 重叠。
