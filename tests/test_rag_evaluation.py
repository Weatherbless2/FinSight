"""R-12 评测指标和报告生成的最小测试。"""

from datetime import date

from tradingagents.rag.evaluation import (
    EvaluationCase,
    EvaluationDocument,
    EvaluationObservation,
    evaluate_strategies,
    evaluate_strategy,
    render_markdown,
    write_report,
)


def make_cases():
    return (
        EvaluationCase(
            question_id="fact-1",
            category="factual",
            ticker="AAPL",
            trade_date=date(2025, 1, 31),
            question="What is revenue?",
            expected_document_ids=("doc-old",),
            expected_sections=("financial_statements",),
            answer_mode="answer_with_citation",
        ),
        EvaluationCase(
            question_id="future-1",
            category="temporal_boundary",
            ticker="AAPL",
            trade_date=date(2025, 1, 31),
            question="Can future data be used?",
            forbidden_document_ids=("doc-future",),
            answer_mode="refuse_future_evidence",
        ),
    )


def make_documents():
    return {
        "doc-old": EvaluationDocument(
            document_id="doc-old",
            ticker="AAPL",
            document_type="quarterly_report",
            available_at=date(2025, 1, 1),
        ),
        "doc-future": EvaluationDocument(
            document_id="doc-future",
            ticker="AAPL",
            document_type="quarterly_report",
            available_at=date(2025, 2, 1),
        ),
    }


def test_metrics_calculate_recall_mrr_citation_and_future_leakage():
    """主路径：命中标准文档时指标为 1，引用未来文档时泄露率为 0.5。"""
    observations = {
        "fact-1": EvaluationObservation(
            retrieved_document_ids=("doc-old",),
            cited_document_ids=("doc-old",),
            elapsed_ms=10,
            input_tokens=100,
            output_tokens=20,
            total_claims=2,
            unsupported_claims=1,
        ),
        "future-1": EvaluationObservation(
            retrieved_document_ids=("doc-future",),
            cited_document_ids=("doc-future",),
            elapsed_ms=20,
            input_tokens=80,
            output_tokens=10,
        ),
    }

    metrics = evaluate_strategy("hybrid", make_cases(), make_documents(), observations)

    assert metrics.recall_at_5 == 1.0
    assert metrics.mrr == 1.0
    assert metrics.citation_coverage == 0.5
    assert metrics.unsupported_claim_rate == 0.5
    assert metrics.future_leakage_rate == 0.5
    assert metrics.p95_latency_ms == 20
    assert metrics.average_total_tokens == 105


def test_report_contains_all_strategies_and_can_be_written(tmp_path):
    """报告边界：多个策略都能写入 JSON 和 Markdown。"""
    observations = {
        case.question_id: EvaluationObservation(
            retrieved_document_ids=case.expected_document_ids,
            cited_document_ids=case.expected_document_ids,
            elapsed_ms=5,
        )
        for case in make_cases()
    }
    report = evaluate_strategies(
        make_cases(),
        make_documents(),
        {"keyword": observations, "hybrid": observations},
    )
    markdown = render_markdown(report)
    json_path, markdown_path = write_report(report, tmp_path)

    assert set(report.strategies) == {"keyword", "hybrid"}
    assert "Recall@5" in markdown
    assert json_path.exists()
    assert markdown_path.exists()
