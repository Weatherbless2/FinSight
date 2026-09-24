"""R-12：RAG 离线评测指标、报告和结果契约。"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class EvaluationCase(BaseModel):
    """从 R-00 清单读取的一道固定评测题。"""

    model_config = ConfigDict(extra="allow")

    question_id: str
    category: str
    ticker: str
    trade_date: date
    question: str
    expected_document_ids: tuple[str, ...] = ()
    forbidden_document_ids: tuple[str, ...] = ()
    expected_sections: tuple[str, ...] = ()
    answer_mode: str


class EvaluationDocument(BaseModel):
    """评测语料中的最小文档日期信息。"""

    model_config = ConfigDict(extra="allow")

    document_id: str
    ticker: str
    document_type: str
    available_at: date


class EvaluationObservation(BaseModel):
    """某个策略对一道题的实际输出和运行指标。"""

    model_config = ConfigDict(extra="forbid")

    retrieved_document_ids: tuple[str, ...] = ()
    cited_document_ids: tuple[str, ...] = ()
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_claims: int = Field(default=0, ge=0)
    unsupported_claims: int = Field(default=0, ge=0)


class StrategyMetrics(BaseModel):
    """一个检索策略在固定评测集上的汇总指标。"""

    strategy: str
    case_count: int
    gold_case_count: int
    refusal_case_count: int
    recall_at_5: float | None
    mrr: float | None
    citation_coverage: float | None
    unsupported_claim_rate: float | None
    future_leakage_rate: float
    p95_latency_ms: float | None
    average_total_tokens: float | None
    category_recall_at_5: dict[str, float]


class EvaluationReport(BaseModel):
    """可以写入 JSON 或转换成 Markdown 的评测报告。"""

    schema_version: str = "rag-eval-report-v1"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    case_count: int
    strategies: dict[str, StrategyMetrics]


def load_evaluation_fixture(path: str | Path) -> tuple[tuple[EvaluationCase, ...], dict[str, EvaluationDocument]]:
    """加载 R-00 固定清单，避免评测输入依赖实时数据。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = tuple(EvaluationCase.model_validate(case) for case in payload["cases"])
    documents = {
        item["document_id"]: EvaluationDocument.model_validate(item)
        for item in payload["corpus"]
    }
    return cases, documents


def _p95(values: Sequence[float]) -> float | None:
    """用最近秩法计算 P95，样本少时不会插入虚构的中间值。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * 0.95))
    return ordered[rank - 1]


def _future_leak(case: EvaluationCase, observation: EvaluationObservation, documents: Mapping[str, EvaluationDocument]) -> bool:
    """检查检索或引用结果是否包含禁止文档或分析日之后公开的文档。"""
    used_ids = set(observation.retrieved_document_ids) | set(observation.cited_document_ids)
    if used_ids & set(case.forbidden_document_ids):
        return True
    trade_date = case.trade_date
    return any(
        document_id in documents and documents[document_id].available_at > trade_date
        for document_id in used_ids
    )


def evaluate_strategy(
    strategy: str,
    cases: Sequence[EvaluationCase],
    documents: Mapping[str, EvaluationDocument],
    observations: Mapping[str, EvaluationObservation],
) -> StrategyMetrics:
    """计算 Recall@5、MRR、引用覆盖率和性能指标。"""
    if not cases:
        raise ValueError("evaluation cases must not be empty")
    missing = [case.question_id for case in cases if case.question_id not in observations]
    if missing:
        raise ValueError(f"missing observations: {', '.join(missing)}")

    recall_values: list[float] = []
    reciprocal_ranks: list[float] = []
    citation_values: list[float] = []
    category_values: dict[str, list[float]] = defaultdict(list)
    elapsed_values: list[float] = []
    token_values: list[int] = []
    future_leak_cases = 0
    total_claims = 0
    unsupported_claims = 0
    gold_case_count = 0

    for case in cases:
        observation = observations[case.question_id]
        retrieved = observation.retrieved_document_ids
        cited = set(observation.cited_document_ids)
        gold = set(case.expected_document_ids)
        if gold:
            gold_case_count += 1
            top5 = set(retrieved[:5])
            recall = len(top5 & gold) / len(gold)
            recall_values.append(recall)
            category_values[case.category].append(recall)
            first_rank = next(
                (rank for rank, document_id in enumerate(retrieved, start=1) if document_id in gold),
                None,
            )
            reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
            citation_values.append(len(cited & gold) / len(gold))
        elif not cited:
            # 拒答题没有标准证据；不引用任何文档才算引用边界通过。
            citation_values.append(1.0)
        else:
            citation_values.append(0.0)

        if _future_leak(case, observation, documents):
            future_leak_cases += 1
        elapsed_values.append(observation.elapsed_ms)
        token_values.append(observation.input_tokens + observation.output_tokens)
        total_claims += observation.total_claims
        unsupported_claims += observation.unsupported_claims

    refusal_case_count = len(cases) - gold_case_count
    return StrategyMetrics(
        strategy=strategy,
        case_count=len(cases),
        gold_case_count=gold_case_count,
        refusal_case_count=refusal_case_count,
        recall_at_5=sum(recall_values) / len(recall_values) if recall_values else None,
        mrr=sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else None,
        citation_coverage=sum(citation_values) / len(citation_values) if citation_values else None,
        unsupported_claim_rate=(unsupported_claims / total_claims if total_claims else None),
        future_leakage_rate=future_leak_cases / len(cases),
        p95_latency_ms=_p95(elapsed_values),
        average_total_tokens=(sum(token_values) / len(token_values) if token_values else None),
        category_recall_at_5={
            category: sum(values) / len(values)
            for category, values in sorted(category_values.items())
        },
    )


def evaluate_strategies(
    cases: Sequence[EvaluationCase],
    documents: Mapping[str, EvaluationDocument],
    strategy_observations: Mapping[str, Mapping[str, EvaluationObservation]],
) -> EvaluationReport:
    """对关键词、向量、Hybrid、Agentic 等多个策略生成同一份报告。"""
    strategies = {
        name: evaluate_strategy(name, cases, documents, observations)
        for name, observations in strategy_observations.items()
    }
    return EvaluationReport(case_count=len(cases), strategies=strategies)


def render_markdown(report: EvaluationReport) -> str:
    """把指标报告转成便于面试复盘的 Markdown 表格。"""
    lines = [
        "# RAG 离线评测报告",
        "",
        f"- 样本数：{report.case_count}",
        f"- 生成时间：{report.generated_at.isoformat()}",
        "",
        "| 策略 | Recall@5 | MRR | 引用覆盖率 | 无依据结论率 | 未来泄露率 | P95(ms) | 平均Token |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metrics in report.strategies.values():
        values = [
            metrics.recall_at_5,
            metrics.mrr,
            metrics.citation_coverage,
            metrics.unsupported_claim_rate,
            metrics.future_leakage_rate,
            metrics.p95_latency_ms,
            metrics.average_total_tokens,
        ]
        formatted = ["-" if value is None else f"{value:.4f}" for value in values]
        lines.append(f"| {metrics.strategy} | " + " | ".join(formatted) + " |")
    return "\n".join(lines) + "\n"


def write_report(report: EvaluationReport, output_dir: str | Path) -> tuple[Path, Path]:
    """同时写入 JSON 原始指标和 Markdown 摘要。"""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "rag-evaluation.json"
    markdown_path = directory / "rag-evaluation.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path
