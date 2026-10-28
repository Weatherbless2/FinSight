"""R-16 FastAPI contract tests without PostgreSQL, Ollama, or an LLM."""

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import scripts.run_rag_demo as demo


class FakeEngine:
    def connect(self):
        raise AssertionError("database access should be stubbed in API contract tests")


class FakeService:
    def __init__(self) -> None:
        self.engine = FakeEngine()

    def search(self, payload: dict) -> dict:
        return {
            "ticker": payload["ticker"].upper(),
            "as_of": payload["as_of"],
            "strategy": payload["strategy"],
            "source": "postgres",
            "persisted": True,
            "expanded_query": payload["question"],
            "elapsed_ms": 1.2,
            "documents": 1,
            "future_safe": True,
            "hits": [],
        }

    def run_agent(self, payload: dict) -> dict:
        return {"ticker": payload["ticker"].upper(), "report": {}, "llm_calls": 0}


def test_health_is_machine_readable():
    response = TestClient(demo.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "rag-demo"}


def test_search_contract_normalizes_ticker_and_rejects_invalid_strategy(monkeypatch):
    monkeypatch.setattr(demo, "get_service", lambda: FakeService())
    client = TestClient(demo.app)

    response = client.post(
        "/api/search",
        json={
            "ticker": " aapl ",
            "as_of": "2025-03-01",
            "strategy": "keyword",
            "top_k": 5,
            "question": "revenue",
        },
    )
    assert response.status_code == 200
    assert response.json()["ticker"] == "AAPL"
    assert response.json()["future_safe"] is True

    invalid = client.post(
        "/api/search",
        json={
            "ticker": "AAPL",
            "as_of": "2025-03-01",
            "strategy": "unsupported",
            "top_k": 5,
            "question": "revenue",
        },
    )
    assert invalid.status_code == 422


def test_agent_contract_uses_structured_error_for_missing_question(monkeypatch):
    monkeypatch.setattr(demo, "get_service", lambda: FakeService())
    response = TestClient(demo.app).post(
        "/api/agent",
        json={"ticker": "AAPL", "as_of": "2025-03-01", "question": ""},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "question"


def test_ingestion_job_not_found_is_404(monkeypatch):
    class MissingJobService(FakeService):
        def __init__(self) -> None:
            self.engine = self

        class _Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, *_args, **_kwargs):
                return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: None))

        def connect(self):
            return self._Connection()

    monkeypatch.setattr(demo, "get_service", lambda: MissingJobService())
    response = TestClient(demo.app).get(f"/api/ingestion-jobs/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "任务不存在"}
