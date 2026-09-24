"""Celery 版财报入库任务；API 进程不默认导入 Celery。"""

from __future__ import annotations

import json
import os
from datetime import date
from uuid import UUID

from celery import Celery
from sqlalchemy import text

from tradingagents.rag.ingestion_pipeline import run_sec_ingestion_pipeline
from tradingagents.rag.postgres import create_postgres_engine


def _create_app() -> Celery:
    """创建统一的 Redis Broker 和结果后端配置。"""
    broker = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    app = Celery("tradeagent", broker=broker, backend=broker)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        broker_connection_retry_on_startup=True,
    )
    return app


celery_app = _create_app()


def _update_job(
    job_id: UUID,
    *,
    expressions: dict[str, str] | None = None,
    **values: object,
) -> None:
    """Worker 更新任务表；API 重启后仍可读取任务最终状态。"""
    assignments = [f"{key} = :{key}" for key in values]
    assignments.extend(f"{key} = {value}" for key, value in (expressions or {}).items())
    if "summary" in values:
        assignments = [
            "summary = CAST(:summary AS jsonb)" if item == "summary = :summary" else item
            for item in assignments
        ]
    params = {"job_id": job_id, **values}
    with create_postgres_engine().begin() as connection:
        connection.execute(
            text(f"UPDATE ingestion_jobs SET {', '.join(assignments)} WHERE job_id = :job_id"),
            params,
        )


@celery_app.task(
    bind=True,
    name="tradeagent.ingestion.sync_sec",
    autoretry_for=(TimeoutError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_sec_ingestion_task(self, job_id: str, ticker: str, as_of: str, limit_per_form: int) -> dict:
    """Celery Worker 执行完整 SEC 增量管线，结果写回 PostgreSQL。"""
    parsed_job_id = UUID(job_id)
    _update_job(
        parsed_job_id,
        status="running",
        progress="Celery Worker 正在从 SEC 发现财报",
        expressions={"started_at": "CURRENT_TIMESTAMP"},
    )
    try:
        summary = run_sec_ingestion_pipeline(
            ticker,
            date.fromisoformat(as_of),
            limit_per_form=limit_per_form,
        )
    except Exception as exc:  # noqa: BLE001 - 状态必须回写给任务中心
        _update_job(
            parsed_job_id,
            status="failed",
            progress="Celery Worker 执行失败",
            error_message=f"{type(exc).__name__}: {exc}"[:4000],
            expressions={"finished_at": "CURRENT_TIMESTAMP"},
        )
        raise
    _update_job(
        parsed_job_id,
        status="succeeded",
        progress="Celery Worker 已完成下载、切分、入库和向量化",
        summary=json.dumps(summary, ensure_ascii=False),
        expressions={"finished_at": "CURRENT_TIMESTAMP"},
    )
    return summary
