# R-12：RAG 离线评测回归

## 问题

如何用固定问题集比较关键词、向量、Hybrid 和 Agentic Retrieval，而不是凭感觉声称“效果提升”？

## 做了什么

- 新增 `EvaluationCase`、`EvaluationDocument` 和 `EvaluationObservation`，统一评测输入与策略输出。
- 新增 `evaluate_strategy()`，计算 Recall@5、MRR、引用覆盖率、无依据结论率、未来泄露率、P95 延迟、平均 Token 和分类 Recall。
- 新增 `evaluate_strategies()`，一次比较多个策略。
- 未来泄露检查同时看禁止文档 ID 和文档 `available_at > trade_date`。
- 新增 JSON 原始报告和 Markdown 摘要生成。
- 新增 `scripts/run_rag_eval.py`，读取实际策略输出文件后生成报告。
- 测试使用小型确定性观察值验证公式，不把模拟数据当作真实项目指标。

## 目的

评测指标必须可重复、可审计。Recall@5/MRR 衡量找没找到标准证据，引用覆盖率衡量报告是否引用了标准文档，无依据结论率衡量回答是否超出证据，未来泄露率是金融场景硬安全指标，P95 和 Token 用于工程成本比较。

## 使用方式

实际检索器需要先输出如下结构：

    {
      "strategies": {
        "keyword": {
          "aapl-fact-01": {
            "retrieved_document_ids": ["aapl-2025q1-10q"],
            "cited_document_ids": ["aapl-2025q1-10q"],
            "elapsed_ms": 42.1,
            "input_tokens": 380,
            "output_tokens": 0
          }
        }
      }
    }

然后执行：

    .venv/bin/python scripts/run_rag_eval.py --outputs results/rag_eval/strategy_outputs.json

报告会写入：

    results/rag_eval/rag-evaluation.json
    results/rag_eval/rag-evaluation.md

## 真实执行结果

R-12-D 已在本地 Docker Desktop PostgreSQL 中完成真实评测：

- 真实文档：13 份；真实 Chunk：1,092 个。
- Embedding：1,092/1,092 成功，模型为 Ollama `nomic-embed-text`，存储维度为 1,536。
- 固定问题：30 道，事实、对比、推理、时间边界、证据不足各 6 道。
- 四种策略均使用 PostgreSQL 的 `content_tsv` 或 pgvector `embedding <=> query_vector`，并执行股票和 `available_at <= trade_date` 过滤。

| 策略 | Recall@5 | MRR | 引用覆盖率 | 未来泄露率 | P95(ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| keyword | 0.8056 | 0.7500 | 0.8833 | 0.0000 | 6.990 |
| vector | 1.0000 | 0.8704 | 1.0000 | 0.0000 | 56.580 |
| hybrid | 0.9722 | 0.8704 | 0.9833 | 0.0000 | 55.803 |
| agentic | 0.8333 | 0.8333 | 0.9000 | 0.0000 | 59.951 |

完整 HTML 报告：`docs/R-12-D-evaluation-report.html`。

## 测试与结果

    .venv/bin/pytest -q tests/test_rag_evaluation.py

指标公式测试不调用外部服务；真实评测由 `scripts/run_real_rag_eval.py` 连接 PostgreSQL 和 Ollama 执行。完整原始结果保存在 `results/rag_eval/strategy_outputs.json` 和 `results/rag_eval/rag-evaluation.json`。

## 设计取舍

P95 使用最近秩法，样本少时不插入虚构中间值；无生成回答时 `unsupported_claim_rate` 返回空值，而不是把“没有评测”伪装成 0。报告输入和评测逻辑分离，后续接入 PostgreSQL 或真实 Agent 只需生成 `EvaluationObservation`。

## 30 秒面试答案

我先固定了 30 道金融问题和标准证据，再用统一 Observation 记录每种检索策略的文档排名、引用、耗时和 Token。评测器统一计算 Recall@5、MRR、引用覆盖率、无依据结论率、未来泄露率和 P95，未来泄露率非零直接视为安全失败，避免用主观感受评价 RAG。

## 当前限制与下一步

本次评测只覆盖检索层，没有调用回答模型，因此 `unsupported_claim_rate` 仍为未评测，平均 Token 是查询文本估算值，不是回答模型成本。Agentic 有一个 MSFT 推理题只召回了两个标准文档中的一个，后续需要分析查询改写和停止条件。

下一步是 R-13：把真实检索结果接入基本面分析师，完成“检索 → 证据校验 → Agent 报告”的端到端验证，并记录回答模型的引用、无依据结论和 Token 成本。
