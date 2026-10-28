-- R-05：BGE-M3 1024 维向量独立存储，不覆盖旧 document_chunks.embedding VECTOR(1536)。
BEGIN;

CREATE TABLE IF NOT EXISTS embedding_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    content_count INTEGER NOT NULL DEFAULT 0 CHECK (content_count >= 0),
    success_count INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS document_embeddings_bge_m3 (
    chunk_id TEXT PRIMARY KEY REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions = 1024),
    content_hash CHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    embedding VECTOR(1024) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed')),
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    embedded_at TIMESTAMPTZ,
    UNIQUE (chunk_id, model_name, model_version)
);

CREATE INDEX IF NOT EXISTS idx_document_embeddings_bge_m3_vector
    ON document_embeddings_bge_m3 USING hnsw (embedding vector_cosine_ops);

COMMIT;
