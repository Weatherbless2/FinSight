"""R-09 candidate reranking, duplicate suppression and deterministic fallback."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from tradingagents.rag.retrieval import RetrievalHit

Reranker = Callable[[str, Sequence[str]], Sequence[float]]


@dataclass(frozen=True)
class RerankOutcome:
    hits: tuple[RetrievalHit, ...]
    used_fallback: bool
    error: str | None = None


def _content_key(content: str) -> str:
    return hashlib.sha256(" ".join(content.split()).lower().encode()).hexdigest()


def _deduplicate(hits: Sequence[RetrievalHit], *, max_per_document: int) -> tuple[RetrievalHit, ...]:
    seen_content: set[str] = set()
    document_counts: dict[str, int] = {}
    result: list[RetrievalHit] = []
    for hit in hits:
        content_key = _content_key(hit.content)
        if content_key in seen_content:
            continue
        count = document_counts.get(hit.document_id, 0)
        if count >= max_per_document:
            continue
        seen_content.add(content_key)
        document_counts[hit.document_id] = count + 1
        result.append(hit)
    return tuple(result)


def rerank_hits(
    query: str,
    candidates: Sequence[RetrievalHit],
    reranker: Reranker,
    *,
    top_k: int = 5,
    max_per_document: int = 3,
) -> RerankOutcome:
    """Rerank RRF candidates and retain an explainable RRF fallback."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1 or (candidates and top_k > len(candidates)):
        raise ValueError("top_k must be positive and no greater than candidates")
    if max_per_document < 1:
        raise ValueError("max_per_document must be positive")
    fallback = _deduplicate(candidates, max_per_document=max_per_document)[:top_k]
    try:
        scores = tuple(float(score) for score in reranker(query, [hit.content for hit in candidates]))
        if len(scores) != len(candidates):
            raise ValueError("reranker returned an unexpected score count")
        ranked = sorted(
            zip(scores, candidates, strict=True),
            key=lambda item: (-item[0], item[1].chunk_id),
        )
        scored_hits = [replace(hit, rerank_score=score) for score, hit in ranked]
        return RerankOutcome(
            _deduplicate(scored_hits, max_per_document=max_per_document)[:top_k],
            used_fallback=False,
        )
    except Exception as exc:  # noqa: BLE001 - failed rerank must remain usable
        return RerankOutcome(fallback, used_fallback=True, error=f"{type(exc).__name__}: {exc}")
