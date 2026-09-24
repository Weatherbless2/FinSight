"""读取 R-00 清单和各策略输出，生成 R-12 JSON/Markdown 评测报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.rag.evaluation import (
    EvaluationObservation,
    evaluate_strategies,
    load_evaluation_fixture,
    write_report,
)


def load_strategy_outputs(path: Path) -> dict[str, dict[str, EvaluationObservation]]:
    """把外部运行器的 JSON 输出转换成统一评测观察值。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        strategy: {
            question_id: EvaluationObservation.model_validate(observation)
            for question_id, observation in observations.items()
        }
        for strategy, observations in payload["strategies"].items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/rag_eval_cases.json",
        help="R-00 固定评测清单路径",
    )
    parser.add_argument(
        "--outputs",
        required=True,
        help="各策略对 30 道题的 JSON 输出",
    )
    parser.add_argument(
        "--output-dir",
        default="results/rag_eval",
        help="JSON/Markdown 报告输出目录",
    )
    args = parser.parse_args()

    cases, documents = load_evaluation_fixture(args.fixture)
    observations = load_strategy_outputs(Path(args.outputs))
    report = evaluate_strategies(cases, documents, observations)
    json_path, markdown_path = write_report(report, args.output_dir)
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")


if __name__ == "__main__":
    main()
