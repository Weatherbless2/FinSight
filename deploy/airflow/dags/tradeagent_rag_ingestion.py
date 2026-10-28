"""Airflow orchestration contract for the TradeAgent RAG ingestion chain.

The DAG only schedules the existing idempotent task boundary. PostgreSQL and
MinIO remain the authoritative stores; Airflow metadata is not business data.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator


def discover_filings(**context):
    """Run the repository discovery command with Airflow-provided dates."""
    from tradingagents.rag.sec_filings import SECClient

    return [
        item.model_dump(mode="json")
        for item in SECClient().discover_filings(
            context["params"]["ticker"],
            as_of=datetime.strptime(context["ds"], "%Y-%m-%d").date(),
            forms=("10-K", "10-Q", "8-K"),
            limit_per_form=context["params"].get("limit_per_form", 1),
        )
    ]
    )


def ingest_filings(**context):
    """Run the existing idempotent SEC ingestion pipeline."""
    from tradingagents.rag.ingestion_pipeline import run_sec_ingestion_pipeline

    return run_sec_ingestion_pipeline(
        context["params"]["ticker"],
        datetime.strptime(context["ds"], "%Y-%m-%d").date(),
        limit_per_form=context["params"].get("limit_per_form", 1),
    )


with DAG(
    dag_id="tradeagent_rag_ingestion",
    schedule="0 3 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "tradeagent",
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
    },
    params={"ticker": "AAPL", "limit_per_form": 1},
    tags=["tradeagent", "rag"],
) as dag:
    discover = PythonOperator(task_id="discover_sec_filings", python_callable=discover_filings)
    ingest = PythonOperator(task_id="ingest_parse_chunk_embed", python_callable=ingest_filings)
    discover >> ingest
