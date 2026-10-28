from tradingagents.observability.rag_metrics import RagTrace


def test_rag_trace_collects_latency_tokens_and_errors_without_secrets():
    trace = RagTrace("run-1", "trace-1", "NVDA", "2025-03-01", "hybrid")
    trace.add_event("retrieval", elapsed_ms=12.3456, token_in=10, token_out=2)
    trace.add_event("llm", elapsed_ms=20, token_in=5, token_out=8, error_code="TIMEOUT")

    assert trace.summary() == {
        "run_id": "run-1",
        "trace_id": "trace-1",
        "ticker": "NVDA",
        "trade_date": "2025-03-01",
        "strategy": "hybrid",
        "event_count": 2,
        "total_elapsed_ms": 32.346,
        "token_in": 15,
        "token_out": 10,
        "errors": 1,
    }
