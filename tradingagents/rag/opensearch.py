"""R-06 OpenSearch BM25 mapping and filtered query contracts."""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from tradingagents.rag.embeddings import BGE_M3_VECTOR_DIMENSIONS


class OpenSearchHTTPError(RuntimeError):
    """OpenSearch returned a non-success response or a rejected bulk item."""


@dataclass(frozen=True)
class OpenSearchClient:
    """Small HTTP adapter for index lifecycle, bulk projection, and search."""

    base_url: str = "http://127.0.0.1:9200"
    username: str | None = None
    password: str | None = None
    timeout_seconds: float = 10.0
    transport: Callable[[str, str, Any, dict[str, str]], dict[str, Any]] | None = None

    def _request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = {"content-type": "application/json", **(headers or {})}
        if self.transport is not None:
            return self.transport(method, path, body, request_headers)
        auth = (self.username, self.password) if self.username else None
        is_json = request_headers["content-type"] == "application/json"
        response = httpx.request(
            method,
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
            json=body if is_json else None,
            content=body if not is_json else None,
            headers=request_headers,
            auth=auth,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 300:
            raise OpenSearchHTTPError(
                f"OpenSearch {method} {path} returned {response.status_code}: {response.text[:500]}"
            )
        return response.json() if response.content else {}

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/_cluster/health")

    def create_index(self, index: str, *, index_version: str = "v1") -> dict[str, Any]:
        if not index or "/" in index or " " in index:
            raise ValueError("index must be a path-safe name")
        return self._request("PUT", f"/{index}", build_bm25_mapping(index_version=index_version))

    def delete_index(self, index: str) -> dict[str, Any]:
        if not index or "/" in index or " " in index:
            raise ValueError("index must be a path-safe name")
        return self._request("DELETE", f"/{index}")

    def bulk_upsert(self, index: str, documents: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not documents:
            return {"errors": False, "items": []}
        lines: list[str] = []
        for document in documents:
            chunk_id = str(document.get("chunk_id", "")).strip()
            if not chunk_id:
                raise ValueError("each OpenSearch document requires chunk_id")
            lines.append(json.dumps({"index": {"_index": index, "_id": chunk_id}}, ensure_ascii=False))
            lines.append(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
        result = self._request(
            "POST",
            "/_bulk",
            "\n".join(lines) + "\n",
            headers={"content-type": "application/x-ndjson"},
        )
        if result.get("errors"):
            failed = [
                item for item in result.get("items", [])
                if item.get("index", {}).get("status", 500) >= 300
            ]
            raise OpenSearchHTTPError(f"OpenSearch bulk upsert failed for {len(failed)} item(s)")
        return result

    def search(self, index: str, query: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/{index}/_search", query)


def build_chunk_projection(
    *,
    chunk_id: str,
    document_id: str,
    ticker: str,
    document_type: str,
    section: str,
    content: str,
    published_at: date,
    available_at: date | None = None,
    tenant_id: str,
    acl_tags: Collection[str] = (),
    content_hash: str,
    embedding: Sequence[float] | None = None,
    embedding_model: str = "bge-m3",
    embedding_version: str = "v1",
    index_version: str = "v1",
) -> dict[str, Any]:
    """Build one idempotent PostgreSQL-to-OpenSearch projection document."""
    if embedding is not None and len(embedding) != BGE_M3_VECTOR_DIMENSIONS:
        raise ValueError(f"embedding must have {BGE_M3_VECTOR_DIMENSIONS} dimensions")
    result = {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "ticker": ticker.strip().upper(),
        "document_type": document_type,
        "section": section,
        "content": content,
        "published_at": published_at.isoformat(),
        "available_at": (available_at or published_at).isoformat(),
        "tenant_id": tenant_id,
        "acl_tags": sorted(set(acl_tags)),
        "content_hash": content_hash,
        "embedding_model": embedding_model,
        "embedding_version": embedding_version,
        "embedding_dimensions": BGE_M3_VECTOR_DIMENSIONS,
        "index_version": index_version,
    }
    if embedding is not None:
        result["embedding"] = [float(value) for value in embedding]
    return result


def build_bm25_mapping(*, index_version: str = "v1") -> dict[str, Any]:
    """Return an explicit mapping for the rebuildable Chunk search projection."""
    if not index_version or "/" in index_version:
        raise ValueError("index_version must be path-safe")
    return {
        "settings": {
            "index": {
                "knn": True,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "analysis": {
                "analyzer": {
                    "financial_text": {
                        "type": "standard",
                        "stop": "_none_",
                    }
                }
            },
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "ticker": {"type": "keyword"},
                "document_type": {"type": "keyword"},
                "section": {"type": "text", "analyzer": "financial_text"},
                "content": {"type": "text", "analyzer": "financial_text"},
                "published_at": {"type": "date", "format": "yyyy-MM-dd"},
                "available_at": {"type": "date", "format": "yyyy-MM-dd"},
                "tenant_id": {"type": "keyword"},
                "acl_tags": {"type": "keyword"},
                "content_hash": {"type": "keyword"},
                "embedding_model": {"type": "keyword"},
                "embedding_version": {"type": "keyword"},
                "embedding_dimensions": {"type": "integer"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": BGE_M3_VECTOR_DIMENSIONS,
                    "method": {
                        "name": "hnsw",
                        "engine": "lucene",
                        "space_type": "cosinesimil",
                    },
                },
                "index_version": {"type": "keyword"},
            },
        },
        "_meta": {"index_version": index_version, "source_of_truth": "postgresql"},
    }


def build_bm25_query(
    query: str,
    *,
    ticker: str,
    trade_date: date,
    tenant_id: str,
    acl_tags: Collection[str] = (),
    document_types: Collection[str] = (),
    top_k: int = 20,
) -> dict[str, Any]:
    """Build a parameterized JSON query; user values never become query syntax."""
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("query must not be empty")
    if not ticker.strip():
        raise ValueError("ticker must not be empty")
    if not tenant_id.strip():
        raise ValueError("tenant_id must not be empty")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    filters: list[dict[str, Any]] = [
        {"term": {"ticker": ticker.strip().upper()}},
        {"term": {"tenant_id": tenant_id.strip()}},
        {"range": {"available_at": {"lte": trade_date.isoformat()}}},
    ]
    if acl_tags:
        filters.append({"terms": {"acl_tags": sorted(set(acl_tags))}})
    if document_types:
        filters.append({"terms": {"document_type": sorted(set(document_types))}})
    return {
        "size": top_k,
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": filters,
                "must": [{"match": {"content": {"query": normalized, "operator": "or"}}}],
            }
        },
        "_source": [
            "chunk_id",
            "document_id",
            "ticker",
            "document_type",
            "section",
            "content",
            "published_at",
            "available_at",
            "tenant_id",
            "acl_tags",
            "content_hash",
            "index_version",
        ],
    }


def build_knn_query(
    query_vector: Collection[float],
    *,
    ticker: str,
    trade_date: date,
    tenant_id: str,
    acl_tags: Collection[str] = (),
    document_types: Collection[str] = (),
    top_k: int = 20,
) -> dict[str, Any]:
    """Build a filtered OpenSearch k-NN request for the BGE-M3 index."""
    if len(query_vector) != BGE_M3_VECTOR_DIMENSIONS:
        raise ValueError(f"query vector must have {BGE_M3_VECTOR_DIMENSIONS} dimensions")
    if not all(isinstance(value, (float, int)) for value in query_vector):
        raise ValueError("query vector must contain numeric values")
    bm25 = build_bm25_query(
        "vector-placeholder",
        ticker=ticker,
        trade_date=trade_date,
        tenant_id=tenant_id,
        acl_tags=acl_tags,
        document_types=document_types,
        top_k=top_k,
    )
    filters = bm25["query"]["bool"]["filter"]
    return {
        "size": top_k,
        "query": {
            "knn": {
                "embedding": {
                    "vector": [float(value) for value in query_vector],
                    "k": top_k,
                    "filter": {"bool": {"filter": filters}},
                }
            }
        },
        "_source": bm25["_source"],
    }
