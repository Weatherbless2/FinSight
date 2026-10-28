from tradingagents.rag.cache import build_rag_cache_key


def test_cache_key_contains_versions_and_is_stable():
    kwargs = {
        "kind": "retrieval",
        "ticker": "nvda",
        "trade_date": "2025-03-01",
        "query": "Revenue growth",
        "model_version": "bge-m3-v1",
        "document_version": "docs-v2",
        "tenant_id": "research",
        "acl_fingerprint": "fundamentals|internal",
    }
    first = build_rag_cache_key(**kwargs)
    second = build_rag_cache_key(**{**kwargs, "query": "  revenue   growth "})

    assert first == second
    assert "NVDA" in first
    assert "bge-m3-v1" in first
    assert "docs-v2" in first
