"""R-07：Embedding Provider 抽象和片段向量生成。"""

from __future__ import annotations

import hashlib
import math
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tradingagents.rag.chunking import DocumentChunk

POSTGRES_VECTOR_DIMENSIONS = 1536
BGE_M3_VECTOR_DIMENSIONS = 1024
EmbeddingStatus = Literal["succeeded", "failed"]
VectorStoreContract = Literal["legacy_pgvector_1536", "bge_m3_1024"]


class EmbeddingModelConfig(BaseModel):
    """Embedding 模型配置，并与 R-03 的 pgvector 维度契约绑定。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str = Field(default="mock", min_length=1, max_length=64)
    model_name: str = Field(default="hash-embedding", min_length=1, max_length=128)
    model_version: str = Field(default="v1", min_length=1, max_length=64)
    dimensions: int = Field(default=POSTGRES_VECTOR_DIMENSIONS, ge=1)
    native_dimensions: int | None = Field(default=None, ge=1)
    vector_store: VectorStoreContract = "legacy_pgvector_1536"

    @model_validator(mode="after")
    def validate_database_dimension(self) -> EmbeddingModelConfig:
        """禁止生成与数据库 VECTOR(1536) 不一致的向量。"""
        expected_dimensions = (
            BGE_M3_VECTOR_DIMENSIONS
            if self.vector_store == "bge_m3_1024"
            else POSTGRES_VECTOR_DIMENSIONS
        )
        if self.dimensions != expected_dimensions:
            storage_label = (
                f"PostgreSQL VECTOR({expected_dimensions})"
                if self.vector_store == "legacy_pgvector_1536"
                else f"versioned VECTOR({expected_dimensions})"
            )
            raise ValueError(
                f"dimensions must equal {storage_label} ({self.vector_store} contract); "
                "changing dimensions requires a separate versioned database migration"
            )
        if self.native_dimensions is not None and self.native_dimensions > self.dimensions:
            raise ValueError("native_dimensions cannot exceed storage dimensions")
        return self


@dataclass(frozen=True)
class ChunkEmbedding:
    """一个 Chunk 的向量结果，失败记录也保留模型版本方便重试和追踪。"""

    chunk_id: str
    provider: str
    model_name: str
    model_version: str
    status: EmbeddingStatus
    vector: tuple[float, ...] | None = None
    error: str | None = None
    retryable: bool = False


def validate_embedding_vector(
    vector: Sequence[float],
    *,
    dimensions: int,
) -> tuple[float, ...]:
    """校验供应商输出，避免错误维度、NaN 或全零向量进入索引。"""
    values = tuple(float(value) for value in vector)
    if len(values) != dimensions:
        raise ValueError(f"embedding dimension is {len(values)}, expected {dimensions}")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding contains a non-finite value")
    if not any(value != 0.0 for value in values):
        raise ValueError("embedding must not be an all-zero vector")
    return values


class EmbeddingProvider(ABC):
    """真实模型和本地 Mock 共用的最小 Provider 接口。"""

    def __init__(self, config: EmbeddingModelConfig) -> None:
        self.config = config

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """批量把正文转换成向量；真实 API 适配器在后续工单实现。"""

    def embed_chunks(
        self,
        chunks: Sequence[DocumentChunk],
        *,
        batch_size: int = 32,
    ) -> tuple[ChunkEmbedding, ...]:
        """按批次生成结果；某一批失败时保留整批可重试记录。"""
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        results: list[ChunkEmbedding] = []
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [chunk.content for chunk in batch]
            try:
                if any(not text.strip() for text in texts):
                    raise ValueError("chunk content must not be empty")
                vectors = self.embed(texts)
                if len(vectors) != len(batch):
                    raise ValueError("provider returned an unexpected batch size")
                for chunk, raw_vector in zip(batch, vectors, strict=True):
                    results.append(
                        ChunkEmbedding(
                            chunk_id=chunk.metadata.chunk_id,
                            provider=self.config.provider,
                            model_name=self.config.model_name,
                            model_version=self.config.model_version,
                            status="succeeded",
                            vector=validate_embedding_vector(
                                raw_vector,
                                dimensions=self.config.dimensions,
                            ),
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - 整批失败要转成可重试结果
                for chunk in batch:
                    results.append(
                        ChunkEmbedding(
                            chunk_id=chunk.metadata.chunk_id,
                            provider=self.config.provider,
                            model_name=self.config.model_name,
                            model_version=self.config.model_version,
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                            retryable=True,
                        )
                    )
        return tuple(results)



class MockEmbeddingProvider(EmbeddingProvider):
    """基于 SHA-256 的确定性 Mock，不调用网络，专供本地测试和开发。"""

    def __init__(self, config: EmbeddingModelConfig | None = None) -> None:
        super().__init__(config or EmbeddingModelConfig())

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            normalized = text.strip()
            if not normalized:
                raise ValueError("text must not be empty")

            raw_values = []
            for index in range(self.config.dimensions):
                seed = f"{self.config.model_version}:{index}:{normalized}".encode()
                digest = hashlib.sha256(seed).digest()
                raw_values.append((digest[0] / 127.5) - 1.0)

            norm = math.sqrt(sum(value * value for value in raw_values))
            vectors.append(tuple(value / norm for value in raw_values))
        return tuple(vectors)

class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible Embedding 适配器，支持有限重试和自定义 Base URL。"""

    def __init__(
        self,
        config: EmbeddingModelConfig | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: object | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            config
            or EmbeddingModelConfig(
                provider="openai_compatible",
                model_name="text-embedding-3-small",
                model_version="text-embedding-3-small-1536",
            )
        )
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.max_retries = max_retries
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.timeout_seconds = max(0.1, timeout_seconds)
        if client is not None:
            self.client = client
            return
        from openai import OpenAI

        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIEmbeddingProvider")
        resolved_base_url = (
            base_url
            or os.getenv("TRADINGAGENTS_EMBEDDING_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        )
        if not resolved_base_url:
            raise ValueError(
                "TRADINGAGENTS_EMBEDDING_BASE_URL or OPENAI_BASE_URL is required; "
                "refusing to fall back to api.openai.com"
            )
        self.client = OpenAI(
            api_key=resolved_key,
            base_url=resolved_base_url,
            timeout=self.timeout_seconds,
        )

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """调用兼容 OpenAI 的 Embeddings API，并按 index 恢复输入顺序。"""
        if not texts:
            return ()
        payload = list(texts)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.embeddings.create(
                    model=self.config.model_name,
                    input=payload,
                    dimensions=self.config.dimensions,
                )
                data = sorted(response.data, key=lambda item: item.index)
                return tuple(tuple(item.embedding) for item in data)
            except Exception as exc:  # noqa: BLE001 - 转为上层可重试结果
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.backoff_seconds * (2**attempt))
        raise RuntimeError(f"embedding API failed after retries: {last_error}") from last_error


class BGE3EmbeddingProvider(EmbeddingProvider):
    """BGE-M3/TEI adapter with an explicit 1024-dimensional storage contract."""

    def __init__(
        self,
        config: EmbeddingModelConfig | None = None,
        *,
        base_url: str | None = None,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(
            config
            or EmbeddingModelConfig(
                provider="tei",
                model_name="BAAI/bge-m3",
                model_version="bge-m3-1024-v1",
                dimensions=BGE_M3_VECTOR_DIMENSIONS,
                vector_store="bge_m3_1024",
            )
        )
        if self.config.vector_store != "bge_m3_1024":
            raise ValueError("BGE3EmbeddingProvider requires the bge_m3_1024 contract")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.base_url = (base_url or os.getenv("BGE_M3_TEI_URL") or "http://127.0.0.1:8080").rstrip("/")
        self.max_retries = max_retries
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.timeout_seconds = max(0.1, timeout_seconds)

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Call the TEI /embed endpoint and validate every returned vector."""
        if not texts:
            return ()
        import httpx

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    urljoin(self.base_url + "/", "embed"),
                    json={"inputs": list(texts)},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                raw_vectors = response.json()
                if not isinstance(raw_vectors, list) or len(raw_vectors) != len(texts):
                    raise ValueError("TEI returned an unexpected batch size")
                return tuple(
                    validate_embedding_vector(vector, dimensions=BGE_M3_VECTOR_DIMENSIONS)
                    for vector in raw_vectors
                )
            except Exception as exc:  # noqa: BLE001 - preserve retryable provider errors
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.backoff_seconds * (2**attempt))
        raise RuntimeError(f"BGE-M3 TEI embedding failed after retries: {last_error}") from last_error

class OllamaEmbeddingProvider(EmbeddingProvider):
    """调用本机 Ollama 的 Embedding 模型，并适配 PostgreSQL 1536 维存储。"""

    def __init__(
        self,
        config: EmbeddingModelConfig | None = None,
        *,
        base_url: str | None = None,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(
            config
            or EmbeddingModelConfig(
                provider="ollama",
                model_name=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
                model_version="nomic-embed-text-768",
                dimensions=POSTGRES_VECTOR_DIMENSIONS,
                native_dimensions=768,
            )
        )
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.base_url = (
            base_url
            or os.getenv("OLLAMA_EMBEDDING_BASE_URL")
            or os.getenv("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        self.max_retries = max_retries
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.timeout_seconds = max(0.1, timeout_seconds)

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """调用 /api/embed，并将原生 768 维向量补齐到 1536 维。"""
        if not texts:
            return ()
        import httpx

        payload = {"model": self.config.model_name, "input": list(texts)}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    urljoin(self.base_url + "/", "api/embed"),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                raw_vectors = response.json().get("embeddings")
                if not isinstance(raw_vectors, list) or len(raw_vectors) != len(texts):
                    raise ValueError("Ollama returned an unexpected batch size")
                return self._normalize_vectors(raw_vectors)
            except Exception as exc:  # noqa: BLE001 - 转成上层可重试结果
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.backoff_seconds * (2**attempt))

        # Ollama 0.1/0.2 exposes only the singular /api/embeddings endpoint.
        # Keep this compatibility path so older lightweight installs work too.
        try:
            raw_vectors = []
            for text in texts:
                response = httpx.post(
                    urljoin(self.base_url + "/", "api/embeddings"),
                    json={"model": self.config.model_name, "prompt": text},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                raw_vector = response.json().get("embedding")
                if not isinstance(raw_vector, list):
                    raise ValueError("Ollama returned no embedding")
                raw_vectors.append(raw_vector)
            return self._normalize_vectors(raw_vectors)
        except Exception as exc:  # noqa: BLE001 - preserve useful final error
            last_error = exc
        raise RuntimeError(f"Ollama embedding API failed after retries: {last_error}") from last_error

    def _normalize_vectors(self, raw_vectors: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
        native_dimensions = self.config.native_dimensions
        if native_dimensions is None:
            raise ValueError("native_dimensions is required for Ollama provider")
        vectors = []
        for raw_vector in raw_vectors:
            native = validate_embedding_vector(raw_vector, dimensions=native_dimensions)
            padded = native + (0.0,) * (self.config.dimensions - native_dimensions)
            vectors.append(validate_embedding_vector(padded, dimensions=self.config.dimensions))
        return tuple(vectors)
