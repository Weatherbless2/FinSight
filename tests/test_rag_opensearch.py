from datetime import date

import pytest

from tradingagents.rag.embeddings import BGE_M3_VECTOR_DIMENSIONS
from tradingagents.rag.opensearch import (
    OpenSearchClient,
    build_bm25_mapping,
    build_bm25_query,
    build_chunk_projection,
    build_knn_query,
)


def test_mapping_has_exact_and_full_text_fields_and_bge_dimension():
    mapping = build_bm25_mapping(index_version="rag-v1")
    properties = mapping["mappings"]["properties"]

    assert properties["ticker"] == {"type": "keyword"}
    assert properties["content"]["type"] == "text"
    assert properties["published_at"]["type"] == "date"
    assert properties["embedding"]["dimension"] == BGE_M3_VECTOR_DIMENSIONS
    assert mapping["_meta"]["source_of_truth"] == "postgresql"


def test_bm25_query_filters_ticker_date_tenant_acl_and_types():
    query = build_bm25_query(
        "NVDA revenue growth",
        ticker="nvda",
        trade_date=date(2025, 3, 1),
        tenant_id="research",
        acl_tags=["fundamentals", "internal"],
        document_types=["annual_report"],
    )
    filters = query["query"]["bool"]["filter"]

    assert {"term": {"ticker": "NVDA"}} in filters
    assert {"term": {"tenant_id": "research"}} in filters
    assert {"range": {"available_at": {"lte": "2025-03-01"}}} in filters
    assert {"terms": {"acl_tags": ["fundamentals", "internal"]}} in filters
    assert {"terms": {"document_type": ["annual_report"]}} in filters
    assert query["size"] == 20


@pytest.mark.parametrize("kwargs", [{"query": "  "}, {"ticker": ""}, {"tenant_id": ""}])
def test_bm25_query_rejects_missing_required_filters(kwargs):
    values = {
        "query": "revenue",
        "ticker": "NVDA",
        "trade_date": date(2025, 3, 1),
        "tenant_id": "research",
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        build_bm25_query(**values)


def test_knn_query_uses_same_date_and_acl_filters():
    query = build_knn_query(
        [0.1] * BGE_M3_VECTOR_DIMENSIONS,
        ticker="NVDA",
        trade_date=date(2025, 3, 1),
        tenant_id="research",
        acl_tags=["internal"],
    )
    filters = query["query"]["knn"]["embedding"]["filter"]["bool"]["filter"]

    assert query["query"]["knn"]["embedding"]["k"] == 20
    assert {"term": {"ticker": "NVDA"}} in filters
    assert {"range": {"available_at": {"lte": "2025-03-01"}}} in filters
    assert {"terms": {"acl_tags": ["internal"]}} in filters


def test_knn_query_rejects_wrong_dimensions():
    with pytest.raises(ValueError, match="1024"):
        build_knn_query(
            [0.1] * 3,
            ticker="NVDA",
            trade_date=date(2025, 3, 1),
            tenant_id="research",
        )


def test_chunk_projection_and_bulk_upsert_are_idempotent_contracts():
    requests = []

    def transport(method, path, body, headers):
        requests.append((method, path, body, headers))
        return {"errors": False, "items": []} if path == "/_bulk" else {"acknowledged": True}

    projection = build_chunk_projection(
        chunk_id="chunk-1",
        document_id="doc-1",
        ticker="aapl",
        document_type="annual_report",
        section="Risk Factors",
        content="Revenue risk",
        published_at=date(2025, 1, 1),
        tenant_id="default",
        acl_tags=("research",),
        content_hash="a" * 64,
        embedding=[0.1] * 1024,
    )
    result = OpenSearchClient(transport=transport).bulk_upsert("rag-v1", [projection])

    assert result["errors"] is False
    method, path, body, headers = requests[0]
    assert (method, path) == ("POST", "/_bulk")
    assert headers["content-type"] == "application/x-ndjson"
    assert '"_id": "chunk-1"' in body
