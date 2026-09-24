"""公开金融文档的下载、哈希和原文落盘。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from tradingagents.rag.documents import DocumentType, FinancialDocumentMetadata

DEFAULT_USER_AGENT = "TradeAgent/0.1 (local financial research)"
DEFAULT_MAX_BYTES = 25 * 1024 * 1024


class DocumentIngestionError(RuntimeError):
    """可向导入命令和后续 ingestion_runs 表传递的稳定错误。"""


@dataclass(frozen=True)
class FetchedDocument:
    """下载结果；原文保持 bytes，避免 PDF 或非 UTF-8 文件被破坏。"""

    source_url: str
    content: bytes
    content_type: str
    fetched_at: datetime

    @property
    def source_hash(self) -> str:
        """使用原始 bytes 计算 SHA-256，作为文档去重和引用指纹。"""
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class StoredDocument:
    """原文和清单落盘后的路径，供后续解析工单继续使用。"""

    raw_path: Path
    manifest_path: Path
    metadata: FinancialDocumentMetadata


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DocumentIngestionError("source_url must be an absolute http(s) URL")


def fetch_document(
    source_url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 20.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> FetchedDocument:
    """下载一个公开文档，并在进入解析前限制体积和记录内容类型。"""
    _validate_http_url(source_url)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    try:
        response = requests.get(
            source_url,
            headers={"User-Agent": user_agent, "Accept": "*/*"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DocumentIngestionError(f"download failed: {exc}") from exc

    content = response.content
    if not content:
        raise DocumentIngestionError("download returned an empty body")
    if len(content) > max_bytes:
        raise DocumentIngestionError(
            f"document exceeds max_bytes={max_bytes}: received {len(content)}"
        )

    content_type = response.headers.get("content-type", "application/octet-stream")
    return FetchedDocument(
        source_url=source_url,
        content=content,
        content_type=content_type.split(";", 1)[0].strip().lower(),
        fetched_at=datetime.now(timezone.utc),
    )


def build_document_metadata(
    fetched: FetchedDocument,
    *,
    document_id: str,
    ticker: str,
    document_type: DocumentType,
    title: str,
    published_at: date,
    available_at: date,
    fiscal_period: str | None = None,
    period_end: date | None = None,
    language: str = "en",
) -> FinancialDocumentMetadata:
    """把下载结果转换成 R-01 契约，并自动写入实际内容哈希。"""
    return FinancialDocumentMetadata(
        document_id=document_id,
        ticker=ticker,
        document_type=document_type,
        title=title,
        source_url=fetched.source_url,
        source_hash=fetched.source_hash,
        published_at=published_at,
        available_at=available_at,
        fiscal_period=fiscal_period,
        period_end=period_end,
        language=language,
    )


def store_raw_document(
    fetched: FetchedDocument,
    metadata: FinancialDocumentMetadata,
    output_dir: str | Path,
) -> StoredDocument:
    """按文档 ID落盘原文和导入清单；同一内容重复写入不会覆盖不同哈希。"""
    if metadata.source_url != fetched.source_url:
        raise DocumentIngestionError("metadata source_url does not match fetched URL")
    if metadata.source_hash != fetched.source_hash:
        raise DocumentIngestionError("metadata source_hash does not match content")

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{metadata.document_id}-{metadata.source_hash[:12]}"
    raw_path = root / f"{stem}.raw"
    manifest_path = root / f"{stem}.json"

    # 文档 ID 已经由 Pydantic 限制字符，路径仍只在指定 output_dir 下生成。
    raw_path.write_bytes(fetched.content)
    manifest = {
        "status": "succeeded",
        "document_id": metadata.document_id,
        "source_url": metadata.source_url,
        "source_hash": metadata.source_hash,
        "content_type": fetched.content_type,
        "byte_count": len(fetched.content),
        "fetched_at": fetched.fetched_at.isoformat(),
        "metadata": metadata.model_dump(mode="json"),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + os.linesep,
        encoding="utf-8",
    )
    return StoredDocument(raw_path, manifest_path, metadata)


def write_failed_manifest(
    *,
    source_url: str,
    output_dir: str | Path,
    error: Exception,
    document_id: str = "unknown",
) -> Path:
    """下载失败时留下可审计记录，供后续 ingestion_runs 导入。"""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    # 失败场景不能信任 CLI/模型传入的 document_id，文件名只使用哈希。
    key = hashlib.sha256(
        f"{document_id}\0{source_url}".encode()
    ).hexdigest()[:16]
    path = root / f"failed-{key}.json"
    payload = {
        "status": "failed",
        "document_id": document_id,
        "source_url": source_url,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + os.linesep,
        encoding="utf-8",
    )
    return path
