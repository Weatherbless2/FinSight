# R-01：MinIO 原始文档管理实施记录

`tradingagents/rag/storage.py` 新增 `MinioObjectStorage`。适配器通过 MinIO Python SDK 写入 S3-compatible 对象，使用 `ticker/document_type/published_at/document_id/source_hash.source` 路径契约，且把完整 SHA-256 写入 `X-Amz-Meta-Source-Hash`。同一 key 同一哈希直接返回已有版本；同一 key 不同哈希拒绝写入；读取时可按 `version_id` 读取并校验哈希。

`tradingagents/rag/sec_ingestion.py` 支持把下载结果同时写入对象存储和本地解析目录，`TRADINGAGENTS_OBJECT_STORAGE=minio` 时由 `ingestion_pipeline.py` 创建 MinIO 适配器，返回 bucket、object_key 和 object_version，便于 PostgreSQL 后续保存对象引用。

验证：`tests/test_rag_storage.py` 和 `tests/test_sec_ingestion.py` 覆盖本地实现、假 MinIO 客户端、幂等、冲突、读取校验和批量导入对象引用；本轮共 22 项组合测试通过。真实 MinIO 容器因 Docker Registry 网络超时尚未启动，Compose 服务定义已加入。
