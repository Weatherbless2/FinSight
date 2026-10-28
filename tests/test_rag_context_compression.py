from datetime import date

from tradingagents.rag.context_compression import compress_evidence
from tradingagents.rag.evidence import EvidenceBundle, EvidenceCitation


def make_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        query="why",
        ticker="NVDA",
        as_of=date(2025, 3, 1),
        citations=(
            EvidenceCitation(
                chunk_id="a",
                document_id="doc-a",
                ticker="NVDA",
                source_url="https://example.com/a",
                available_at=date(2025, 1, 1),
                section="Business",
                text_excerpt="Revenue increased 20 percent because demand improved. Management expects continued growth.",
            ),
            EvidenceCitation(
                chunk_id="b",
                document_id="doc-b",
                ticker="NVDA",
                source_url="https://example.com/b",
                available_at=date(2025, 1, 1),
                section="Risk",
                text_excerpt="Supply constraints remain a risk to margins.",
            ),
        ),
    )


def test_compression_preserves_citation_identity_and_budget():
    result = compress_evidence(make_bundle(), token_budget=12)

    assert result.token_count <= 12
    assert result.original_token_count > result.token_count
    assert result.citations[0].chunk_id == "a"
    assert "[1]" in result.context
    assert "20" in result.context


def test_compression_rejects_invalid_budget():
    import pytest

    with pytest.raises(ValueError):
        compress_evidence(make_bundle(), token_budget=0)
