-- R-17：财报增量入库任务状态。
-- 当前由 FastAPI 后台线程执行；任务表契约可直接迁移到 Redis/Celery Worker。

BEGIN;

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker TEXT NOT NULL CHECK (ticker = upper(ticker)),
    as_of DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    source TEXT NOT NULL DEFAULT 'sec',
    progress TEXT NOT NULL DEFAULT '等待执行',
    summary JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_ticker_created
    ON ingestion_jobs (ticker, created_at DESC);

COMMIT;
