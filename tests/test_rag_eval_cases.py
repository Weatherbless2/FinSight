"""R-00 评测清单的确定性校验，不访问网络、不调用模型。"""

import json
from collections import Counter
from datetime import date
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "rag_eval_cases.json"
REQUIRED_CATEGORIES = {
    "factual",
    "comparison",
    "reasoning",
    "temporal_boundary",
    "insufficient_evidence",
}
REQUIRED_CASE_FIELDS = {
    "question_id",
    "category",
    "ticker",
    "trade_date",
    "question",
    "expected_document_ids",
    "expected_sections",
    "answer_mode",
}


def load_manifest():
    """读取固定评测清单，保证测试输入不会依赖外部服务。"""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_manifest_has_fixed_shape_and_category_balance():
    """确认样本规模和类别比例固定，防止后续偷偷缩小评测集。"""
    manifest = load_manifest()
    cases = manifest["cases"]

    assert len(cases) == 30
    assert len({case["question_id"] for case in cases}) == 30
    assert set(manifest["corpus"][0]) == {
        "document_id",
        "ticker",
        "document_type",
        "available_at",
    }
    assert {case["category"] for case in cases} == REQUIRED_CATEGORIES
    assert Counter(case["category"] for case in cases) == {
        "factual": 6,
        "comparison": 6,
        "reasoning": 6,
        "temporal_boundary": 6,
        "insufficient_evidence": 6,
    }


def test_every_case_has_required_fields_and_known_ticker():
    """确认每道题都有日期、股票和回答模式，便于后续统一评测。"""
    manifest = load_manifest()
    documents = {doc["document_id"]: doc for doc in manifest["corpus"]}

    for case in manifest["cases"]:
        assert case.keys() >= REQUIRED_CASE_FIELDS
        assert case["ticker"] in {"AAPL", "MSFT", "NVDA"}
        assert case["question"].strip()
        assert date.fromisoformat(case["trade_date"])
        for document_id in case["expected_document_ids"]:
            assert document_id in documents
            assert documents[document_id]["ticker"] == case["ticker"]


def test_gold_evidence_is_available_at_trade_date():
    """金融回测只允许使用分析日期前已经公开的标准证据。"""
    manifest = load_manifest()
    documents = {doc["document_id"]: doc for doc in manifest["corpus"]}

    for case in manifest["cases"]:
        trade_date = date.fromisoformat(case["trade_date"])
        for document_id in case["expected_document_ids"]:
            available_at = date.fromisoformat(documents[document_id]["available_at"])
            assert available_at <= trade_date


def test_temporal_and_insufficient_cases_have_no_gold_evidence():
    """未来文档题和证据不足题必须拒答，不得伪造标准文档。"""
    manifest = load_manifest()

    for case in manifest["cases"]:
        if case["answer_mode"] in {
            "refuse_future_evidence",
            "refuse_insufficient_evidence",
        }:
            assert case["expected_document_ids"] == []
            assert case["expected_sections"] == []
