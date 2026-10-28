from datetime import date

import pytest

from tradingagents.rag.documents import FinancialDocumentMetadata
from tradingagents.rag.storage import (
    LocalObjectStorage,
    MinioObjectStorage,
    ObjectStorageError,
    object_key_for,
    store_document_object,
)


def _document() -> FinancialDocumentMetadata:
    return FinancialDocumentMetadata(
        document_id="nvda-2025-10k",
        ticker="NVDA",
        document_type="annual_report",
        title="NVIDIA annual report",
        source_url="https://example.com/nvda.pdf",
        source_hash="a" * 64,
        published_at=date(2025, 2, 26),
        available_at=date(2025, 2, 26),
        language="en",
    )


def test_object_key_is_versioned_and_scoped():
    assert object_key_for(_document(), version="sha256") == (
        "NVDA/annual_report/2025-02-26/nvda-2025-10k/sha256.source"
    )
    with pytest.raises(ValueError, match="path-safe"):
        object_key_for(_document(), version="../escape")


def test_local_storage_is_idempotent_and_reads_verified_bytes(tmp_path):
    storage = LocalObjectStorage(tmp_path)
    key = object_key_for(_document(), version="sha256")
    stored = storage.put("financial-raw", key, b"pdf-bytes", content_type="application/pdf")
    repeated = storage.put("financial-raw", key, b"pdf-bytes", content_type="application/pdf")

    assert repeated == stored
    assert storage.get("financial-raw", key, version=stored.version) == b"pdf-bytes"

    with pytest.raises(ObjectStorageError, match="different content"):
        storage.put("financial-raw", key, b"changed", content_type="application/pdf")


def test_local_storage_rejects_tampered_manifest(tmp_path):
    storage = LocalObjectStorage(tmp_path)
    key = object_key_for(_document(), version="sha256")
    storage.put("financial-raw", key, b"pdf-bytes", content_type="application/pdf")
    raw = tmp_path / "financial-raw" / key
    raw.write_bytes(b"tampered")

    with pytest.raises(ObjectStorageError, match="hash"):
        storage.get("financial-raw", key)


def test_store_document_object_enforces_document_hash(tmp_path):
    storage = LocalObjectStorage(tmp_path)
    metadata = _document().model_copy(update={"source_hash": "b" * 64})

    with pytest.raises(ObjectStorageError, match="source_hash"):
        store_document_object(storage, metadata, b"pdf-bytes")


class _Response:
    def __init__(self, content: bytes):
        self.content = content

    def read(self):
        return self.content

    def close(self):
        pass

    def release_conn(self):
        pass


class _FakeMinio:
    def __init__(self):
        self.objects = {}
        self.buckets = set()

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket):
        self.buckets.add(bucket)

    def stat_object(self, bucket, key, version_id=None):
        item = self.objects[(bucket, key)]
        return type("Stat", (), {"metadata": item[1], "version_id": item[2]})()

    def put_object(self, bucket, key, stream, *, length, content_type, metadata):
        self.objects[(bucket, key)] = (stream.read(), metadata, "version-1")
        return type("Result", (), {"version_id": "version-1"})()

    def get_object(self, bucket, key, version_id=None):
        return _Response(self.objects[(bucket, key)][0])


def test_minio_storage_uses_sha_metadata_and_is_idempotent():
    client = _FakeMinio()
    storage = MinioObjectStorage(client=client)
    payload = b"minio-source"
    first = storage.put("financial-raw", "AAPL/file.source", payload, content_type="text/plain")
    second = storage.put("financial-raw", "AAPL/file.source", payload, content_type="text/plain")

    assert first.version == "version-1"
    assert second == first
    assert storage.get("financial-raw", "AAPL/file.source", version="version-1") == payload


def test_minio_storage_rejects_same_key_with_different_bytes():
    client = _FakeMinio()
    storage = MinioObjectStorage(client=client)
    storage.put("financial-raw", "AAPL/file.source", b"one", content_type="text/plain")

    with pytest.raises(ObjectStorageError, match="different content"):
        storage.put("financial-raw", "AAPL/file.source", b"two", content_type="text/plain")
