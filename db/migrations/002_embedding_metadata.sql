-- R-12-C：记录每个 Chunk 的 Embedding 来源、状态和失败原因。
BEGIN;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS embedding_provider TEXT,
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS embedding_version TEXT,
    ADD COLUMN IF NOT EXISTS embedding_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS embedding_error TEXT,
    ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;

ALTER TABLE document_chunks
    DROP CONSTRAINT IF EXISTS document_chunks_embedding_status_check;

ALTER TABLE document_chunks
    ADD CONSTRAINT document_chunks_embedding_status_check
    CHECK (embedding_status IN ('pending', 'succeeded', 'failed'));

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_status
    ON document_chunks (embedding_status);

COMMIT;
