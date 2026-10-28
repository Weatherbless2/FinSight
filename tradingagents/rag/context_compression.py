"""R-10 evidence compression under an explicit token budget."""

from __future__ import annotations

from dataclasses import dataclass

from tradingagents.rag.chunking import estimate_token_count
from tradingagents.rag.evidence import EvidenceBundle, EvidenceCitation


@dataclass(frozen=True)
class EvidenceSet:
    citations: tuple[EvidenceCitation, ...]
    context: str
    token_count: int
    original_token_count: int
    compression_ratio: float


def _keep_high_value_text(text: str, budget: int) -> str:
    """Keep complete sentences first; never split a numeric token when possible."""
    if estimate_token_count(text) <= budget:
        return text
    pieces = [piece.strip() for piece in text.replace("。", "。\n").replace(".", ".\n").splitlines() if piece.strip()]
    kept: list[str] = []
    for piece in pieces:
        candidate = " ".join(kept + [piece])
        if estimate_token_count(candidate) > budget:
            break
        kept.append(piece)
    if kept:
        return " ".join(kept)
    words = text.split()
    return " ".join(words[: max(1, budget)])


def compress_evidence(
    bundle: EvidenceBundle,
    *,
    token_budget: int = 1600,
) -> EvidenceSet:
    """Build an evidence_set while preserving citation identity and source fields."""
    if token_budget < 1:
        raise ValueError("token_budget must be positive")
    original = sum(estimate_token_count(citation.text_excerpt) for citation in bundle.citations)
    remaining = token_budget
    citations: list[EvidenceCitation] = []
    context_parts: list[str] = []
    for index, citation in enumerate(bundle.citations, start=1):
        if remaining <= 0:
            break
        marker = f"[{index}] "
        marker_budget = estimate_token_count(marker)
        excerpt = _keep_high_value_text(citation.text_excerpt, max(1, remaining - marker_budget))
        if not excerpt.strip():
            continue
        marker = f"[{index}] "
        candidate = f"{marker}{excerpt}"
        while estimate_token_count("\n\n".join(context_parts + [candidate])) > token_budget:
            words = excerpt.split()
            if len(words) <= 1:
                break
            excerpt = " ".join(words[:-1])
            candidate = f"{marker}{excerpt}"
        if estimate_token_count("\n\n".join(context_parts + [candidate])) > token_budget:
            break
        updated = citation.model_copy(update={"text_excerpt": excerpt})
        citations.append(updated)
        context_parts.append(candidate)
        remaining = token_budget - estimate_token_count("\n\n".join(context_parts))
    if not citations:
        raise ValueError("evidence cannot fit token budget")
    context = "\n\n".join(context_parts)
    count = estimate_token_count(context)
    return EvidenceSet(
        citations=tuple(citations),
        context=context,
        token_count=count,
        original_token_count=original,
        compression_ratio=(count / original) if original else 1.0,
    )
