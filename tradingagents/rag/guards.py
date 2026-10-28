"""R-11 deterministic date, ACL and evidence sufficiency guards."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date

from tradingagents.rag.retrieval import RetrievalHit


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    hits: tuple[RetrievalHit, ...]
    reason: str
    error_code: str | None = None


def filter_retrieval_hits(
    hits: Sequence[RetrievalHit],
    *,
    ticker: str,
    trade_date: date,
    allowed_document_ids: Collection[str] | None = None,
    min_evidence: int = 1,
) -> GuardDecision:
    """Apply final deterministic filtering before evidence enters AgentState."""
    if min_evidence < 1:
        raise ValueError("min_evidence must be positive")
    normalized = ticker.strip().upper()
    allowed = set(allowed_document_ids or ())
    filtered = tuple(
        hit
        for hit in hits
        if hit.ticker == normalized
        and hit.available_at <= trade_date
        and (not allowed or hit.document_id in allowed)
    )
    if len(filtered) < min_evidence:
        return GuardDecision(False, filtered, "evidence_insufficient", "EVIDENCE_INSUFFICIENT")
    return GuardDecision(True, filtered, "evidence_allowed")
