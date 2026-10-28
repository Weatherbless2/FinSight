from pathlib import Path


def test_airflow_dag_declares_ordered_idempotent_ingestion_boundary():
    source = Path("deploy/airflow/dags/tradeagent_rag_ingestion.py").read_text(encoding="utf-8")

    assert 'dag_id="tradeagent_rag_ingestion"' in source
    assert 'task_id="discover_sec_filings"' in source
    assert 'task_id="ingest_parse_chunk_embed"' in source
    assert "discover >> ingest" in source
    assert "catchup=False" in source
    assert "max_active_runs=1" in source
