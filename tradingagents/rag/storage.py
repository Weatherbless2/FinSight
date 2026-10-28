"""R-01 原始文档对象存储边界。

The storage contract keeps the ingestion pipeline independent from MinIO's
client library.  The local backend is deterministic for tests and development;
the S3-compatible backend can be enabled when a MinIO endpoint is available.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from tradingagents.rag.documents import FinancialDocumentMetadata


class ObjectStorageError(RuntimeError):
    """A source object could not be written or read consistently."""


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    object_key: str
    version: str
    source_hash: str
    byte_count: int
    content_type: str


class ObjectStorage(Protocol):
    def put(self, bucket: str, object_key: str, content: bytes, *, content_type: str) -> StoredObject:
        """Store immutable content and return its stable content version."""

    def get(self, bucket: str, object_key: str, *, version: str | None = None) -> bytes:
        """Read content by bucket, key and optional version."""


def object_key_for(document: FinancialDocumentMetadata, *, version: str) -> str:
    """Build the frozen R-01 path without accepting arbitrary path segments."""
    if not version or "/" in version or "\\" in version:
        raise ValueError("version must be a non-empty path-safe value")
    return (
        f"{document.ticker}/{document.document_type}/{document.published_at.isoformat()}"
        f"/{document.document_id}/{version}.source"
    )


class LocalObjectStorage:
    """MinIO-compatible local object store used for deterministic tests."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def put(self, bucket: str, object_key: str, content: bytes, *, content_type: str) -> StoredObject:
        if not bucket or not object_key or object_key.startswith("/"):
            raise ValueError("bucket and relative object_key are required")
        source_hash = hashlib.sha256(content).hexdigest()
        version = source_hash
        target = (self.root / bucket / object_key).resolve()
        if self.root not in target.parents:
            raise ValueError("object_key escapes storage root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != content:
            raise ObjectStorageError("object key already contains different content")
        target.write_bytes(content)
        manifest = target.with_suffix(target.suffix + ".json")
        payload = {
            "bucket": bucket,
            "object_key": object_key,
            "version": version,
            "source_hash": source_hash,
            "byte_count": len(content),
            "content_type": content_type,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
        if manifest.exists():
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            immutable_fields = ("bucket", "object_key", "version", "source_hash", "byte_count", "content_type")
            if any(previous.get(field) != payload[field] for field in immutable_fields):
                raise ObjectStorageError("object manifest conflicts with immutable content")
            payload["stored_at"] = previous.get("stored_at", payload["stored_at"])
        else:
            manifest.write_text(json.dumps(payload, indent=2) + os.linesep, encoding="utf-8")
        return StoredObject(bucket, object_key, version, source_hash, len(content), content_type)

    def get(self, bucket: str, object_key: str, *, version: str | None = None) -> bytes:
        target = (self.root / bucket / object_key).resolve()
        if self.root not in target.parents or not target.is_file():
            raise ObjectStorageError("object was not found")
        payload = json.loads(target.with_suffix(target.suffix + ".json").read_text(encoding="utf-8"))
        if version is not None and payload.get("version") != version:
            raise ObjectStorageError("object version does not match")
        content = target.read_bytes()
        if hashlib.sha256(content).hexdigest() != payload.get("source_hash"):
            raise ObjectStorageError("object hash does not match its manifest")
        return content


class MinioObjectStorage:
    """S3-compatible MinIO backend with immutable SHA-256 object metadata."""

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
        client: object | None = None,
    ) -> None:
        if client is None:
            from minio import Minio

            endpoint = endpoint or os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
            access_key = access_key or os.getenv("MINIO_ROOT_USER", "minioadmin")
            secret_key = secret_key or os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
            if secure is None:
                secure = os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"}
            client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.client = client

    def _ensure_bucket(self, bucket: str) -> None:
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    @staticmethod
    def _metadata_hash(metadata: dict[str, str] | None) -> str | None:
        if not metadata:
            return None
        normalized = {str(key).lower(): str(value) for key, value in metadata.items()}
        return normalized.get("x-amz-meta-source-hash") or normalized.get("source-hash")

    def put(self, bucket: str, object_key: str, content: bytes, *, content_type: str) -> StoredObject:
        if not bucket or not object_key or object_key.startswith("/"):
            raise ValueError("bucket and relative object_key are required")
        source_hash = hashlib.sha256(content).hexdigest()
        self._ensure_bucket(bucket)
        try:
            existing = self.client.stat_object(bucket, object_key)
        except Exception:  # noqa: BLE001 - MinIO not-found errors vary by client version
            existing = None
        if existing is not None:
            existing_hash = self._metadata_hash(getattr(existing, "metadata", None))
            if existing_hash is None:
                response = self.client.get_object(bucket, object_key)
                try:
                    existing_hash = hashlib.sha256(response.read()).hexdigest()
                finally:
                    response.close()
                    response.release_conn()
            if existing_hash != source_hash:
                raise ObjectStorageError("object key already contains different content")
            return StoredObject(
                bucket=bucket,
                object_key=object_key,
                version=str(getattr(existing, "version_id", None) or source_hash),
                source_hash=source_hash,
                byte_count=len(content),
                content_type=content_type,
            )
        result = self.client.put_object(
            bucket,
            object_key,
            io.BytesIO(content),
            length=len(content),
            content_type=content_type,
            metadata={"X-Amz-Meta-Source-Hash": source_hash},
        )
        return StoredObject(
            bucket=bucket,
            object_key=object_key,
            version=str(getattr(result, "version_id", None) or source_hash),
            source_hash=source_hash,
            byte_count=len(content),
            content_type=content_type,
        )

    def get(self, bucket: str, object_key: str, *, version: str | None = None) -> bytes:
        response = self.client.get_object(bucket, object_key, version_id=version)
        try:
            content = response.read()
        finally:
            response.close()
            response.release_conn()
        if version is not None:
            stat = self.client.stat_object(bucket, object_key, version_id=version)
            stored_hash = self._metadata_hash(getattr(stat, "metadata", None))
            if stored_hash and stored_hash != hashlib.sha256(content).hexdigest():
                raise ObjectStorageError("object hash does not match its metadata")
        return content


def store_document_object(
    storage: ObjectStorage,
    metadata: FinancialDocumentMetadata,
    content: bytes,
    *,
    bucket: str = "financial-raw",
    content_type: str = "application/octet-stream",
) -> StoredObject:
    """Store a fetched document using the R-01 bucket and hash contract."""
    source_hash = hashlib.sha256(content).hexdigest()
    if source_hash != metadata.source_hash:
        raise ObjectStorageError("metadata source_hash does not match content")
    key = object_key_for(metadata, version=source_hash)
    return storage.put(bucket, key, content, content_type=content_type)
