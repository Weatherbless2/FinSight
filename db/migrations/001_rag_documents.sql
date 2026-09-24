-- R-03：RAG 文档、片段和导入运行记录的初始结构。
-- 该迁移只负责结构，不下载文档、不生成 Embedding。

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL CHECK (ticker = upper(ticker)),
    document_type TEXT NOT NULL CHECK (
        document_type IN (
            'annual_report',
            'quarterly_report',
            'earnings_release',
            'announcement',
            'earnings_call'
        )
    ),
    title TEXT NOT NULL CHECK (length(btrim(title)) > 0),
    source_url TEXT NOT NULL CHECK (source_url ~ '^https?://'),
    source_hash CHAR(64) NOT NULL UNIQUE CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    published_at DATE NOT NULL,
    available_at DATE NOT NULL,
    fiscal_period TEXT,
    period_end DATE,
    language TEXT NOT NULL CHECK (language ~ '^[A-Za-z-]+$'),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (available_at >= published_at)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    section_title TEXT NOT NULL CHECK (length(btrim(section_title)) > 0),
    page_start INTEGER,
    page_end INTEGER,
    char_start INTEGER NOT NULL CHECK (char_start >= 0),
    char_end INTEGER NOT NULL CHECK (char_end > char_start),
    token_count INTEGER NOT NULL CHECK (token_count BETWEEN 1 AND 1000),
    content TEXT NOT NULL CHECK (length(btrim(content)) > 0),
    content_tsv TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', content)
    ) STORED,
    -- R-07 的 Embedding Provider 必须输出 1536 维向量，变更模型需单独迁移。
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (document_id, ordinal),
    CHECK (
        (page_start IS NULL AND page_end IS NULL)
        OR (
            page_start IS NOT NULL
            AND page_end IS NOT NULL
            AND page_start >= 1
            AND page_end >= page_start
        )
    )
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    documents_seen INTEGER NOT NULL DEFAULT 0 CHECK (documents_seen >= 0),
    documents_inserted INTEGER NOT NULL DEFAULT 0 CHECK (documents_inserted >= 0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_ticker_available
    ON documents (ticker, available_at);

CREATE INDEX IF NOT EXISTS idx_documents_type
    ON documents (document_type);

CREATE INDEX IF NOT EXISTS idx_chunks_document_ordinal
    ON document_chunks (document_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv
    ON document_chunks USING GIN (content_tsv);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

COMMIT;
