"""R-13 versioned Redis/cache key contract."""

from __future__ import annotations

import hashlib


def build_rag_cache_key(
    *,
    kind: str,
    ticker: str,
    trade_date: str,
    query: str,
    model_version: str,
    document_version: str,
    tenant_id: str,
    acl_fingerprint: str,
) -> str:
    """Return a stable key that cannot cross model/document/ACL versions."""
    if not kind.strip() or not ticker.strip() or not tenant_id.strip():
        raise ValueError("kind, ticker and tenant_id are required")
    query_hash = hashlib.sha256(" ".join(query.split()).lower().encode()).hexdigest()[:32]
    acl_hash = hashlib.sha256(acl_fingerprint.encode()).hexdigest()[:16]
    return ":".join(
        [
            "tradeagent",
            "rag",
            kind.strip(),
            ticker.strip().upper(),
            trade_date,
            query_hash,
            model_version,
            document_version,
            tenant_id.strip(),
            acl_hash,
        ]
    )
