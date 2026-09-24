"""R-12-D：使用真实 PostgreSQL + pgvector + Ollama 执行四策略评测。

脚本只负责生成统一的 ``EvaluationObservation``，指标计算继续复用
``tradingagents.rag.evaluation``。这样“检索执行”和“指标公式”分开，面试时
可以分别解释数据库查询链路和评测口径，也不会把 Mock 结果混进真实报告。
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

from tradingagents.rag.agentic_retrieval import ConstrainedRetrievalRunner
from tradingagents.rag.chunking import estimate_token_count
from tradingagents.rag.embeddings import OllamaEmbeddingProvider
from tradingagents.rag.evaluation import EvaluationCase, load_evaluation_fixture
from tradingagents.rag.postgres import create_postgres_engine
from tradingagents.rag.postgres_retrieval import PostgresRetriever
from tradingagents.rag.retrieval import RetrievalHit

# 现有 R-12-A 的三个文档使用了 ``-real`` 后缀；评测清单使用稳定的业务 ID。
# 这里做显式别名转换，不修改数据库主键，也不隐藏数据来源差异。
DB_TO_EVALUATION_ID = {
    "aapl-2025q1-10q-real": "aapl-2025q1-10q",
    "nvda-2025-10k-real": "nvda-2025-10k",
}


def default_database_url() -> str:
    """返回 WSL 主机访问 Docker Desktop 映射端口的默认连接串。"""
    return os.getenv(
        "TRADINGAGENTS_DATABASE_URL",
        "postgresql+psycopg://tradingagents:tradingagents_dev_only"
        "@127.0.0.1:5432/tradingagents",
    )


def expand_query(case: EvaluationCase) -> str:
    """把中文业务问题补充为财报常用英文术语，改善英文语料的召回。

    这是确定性的查询规范化，不读取标准答案，也不把 gold 文档 ID 注入查询，
    因此不会造成评测标签泄露。
    """
    replacements = {
        "年度报告": "annual report 10-k",
        "季度报告": "quarterly report 10-q",
        "业绩公告": "earnings release financial results",
        "经营数据": "revenue gross profit operating income net income financial statements",
        "经营表现": "business performance revenue growth",
        "经营变化": "business performance change revenue growth",
        "风险描述": "risk factors risk description",
        "风险": "risk factors",
        "侧重点差异": "focus differences",
        "业务表现变化": "business performance change",
        "可能原因": "management discussion analysis reasons",
        "基本面分析": "fundamental analysis",
        "净利润": "net income",
        "股价收盘价": "stock price closing price",
        "是否可以使用": "available as of date",
        "截至分析日": "available as of analysis date",
        "最新": "latest current",
    }
    normalized = case.question
    for source, target in replacements.items():
        normalized = normalized.replace(source, f" {target} ")
    return f"{case.ticker} {normalized}"


def unique_document_ids(hits: Iterable[RetrievalHit]) -> tuple[str, ...]:
    """按 Chunk 排名折叠成文档排名，保持第一次出现的顺序。"""
    result: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        document_id = DB_TO_EVALUATION_ID.get(hit.document_id, hit.document_id)
        if document_id not in seen:
            result.append(document_id)
            seen.add(document_id)
    return tuple(result)


def check_corpus_coverage(engine, fixture_path: str | Path) -> None:
    """在运行前验证 gold 文档已存在，避免输出无意义的零分报告。"""
    cases, _ = load_evaluation_fixture(fixture_path)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT document_id FROM documents")).scalars().all()
    available = {DB_TO_EVALUATION_ID.get(item, item) for item in rows}
    required = {document_id for case in cases for document_id in case.expected_document_ids}
    missing = sorted(required - available)
    if missing:
        raise RuntimeError("评测语料缺少 gold 文档: " + ", ".join(missing))


def retrieve_for_strategy(
    strategy: str,
    retriever: PostgresRetriever,
    query: str,
    case: EvaluationCase,
) -> tuple[RetrievalHit, ...]:
    """按统一参数调用四种策略，保证比较只改变检索方法。"""
    common = {
        "ticker": case.ticker,
        "as_of": case.trade_date,
        "top_k": 10,
    }
    if strategy == "keyword":
        return retriever.keyword_search(query, **common)
    if strategy == "vector":
        return retriever.vector_search(query, **common)
    if strategy == "hybrid":
        return retriever.hybrid_search(query, **common)
    if strategy == "agentic":
        runner = ConstrainedRetrievalRunner(
            lambda rewritten: retriever.hybrid_search(rewritten, **common),
            query_rewriter=lambda current, _round: expand_query(case)
            if current != expand_query(case)
            else None,
        )
        return runner.run(query).hits
    raise ValueError(f"unknown strategy: {strategy}")


def run_strategy(
    strategy: str,
    cases: tuple[EvaluationCase, ...],
    retriever: PostgresRetriever,
) -> dict[str, dict[str, object]]:
    """逐题运行一个策略并记录排名、引用和耗时。"""
    observations: dict[str, dict[str, object]] = {}
    for case in cases:
        query = expand_query(case)
        started = time.perf_counter()
        hits = retrieve_for_strategy(strategy, retriever, query, case)
        elapsed_ms = (time.perf_counter() - started) * 1000
        retrieved = unique_document_ids(hits)
        # 拒答题保留检索结果用于未来泄露检查，但不产生引用。
        cited = () if case.answer_mode.startswith("refuse_") else retrieved[:5]
        observations[case.question_id] = {
            "retrieved_document_ids": retrieved,
            "cited_document_ids": cited,
            "elapsed_ms": round(elapsed_ms, 3),
            "input_tokens": estimate_token_count(query),
            "output_tokens": 0,
            "total_claims": 0,
            "unsupported_claims": 0,
        }
    return observations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行真实 PostgreSQL RAG 四策略评测")
    parser.add_argument("--fixture", default="tests/fixtures/rag_eval_cases.json")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--output", default="results/rag_eval/strategy_outputs.json")
    parser.add_argument("--candidate-k", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    load_dotenv(".env")
    args = parse_args()
    cases, _ = load_evaluation_fixture(args.fixture)
    engine = create_postgres_engine(args.database_url or default_database_url())
    check_corpus_coverage(engine, args.fixture)
    provider = OllamaEmbeddingProvider()
    retriever = PostgresRetriever(
        engine=engine,
        embedding_provider=provider,
        candidate_k=args.candidate_k,
    )
    strategies = ("keyword", "vector", "hybrid", "agentic")
    payload = {
        "metadata": {
            "source": "PostgreSQL + pgvector + Ollama",
            "fixture": str(args.fixture),
            "case_count": len(cases),
            "embedding_model": provider.config.model_name,
            "embedding_dimensions": provider.config.dimensions,
        },
        "strategies": {},
    }
    for strategy in strategies:
        print(f"running strategy: {strategy}", flush=True)
        payload["strategies"][strategy] = run_strategy(strategy, cases, retriever)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"strategy outputs: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
