from types import SimpleNamespace

import httpx

from tradingagents.rag.embeddings import (
    EmbeddingModelConfig,
    OllamaEmbeddingProvider,
)


def test_ollama_embedding_pads_native_vector_to_pgvector_dimension(monkeypatch):
    native = [0.1] + [0.001] * 767

    def fake_post(url, *, json, timeout):
        assert url.endswith("/api/embed")
        assert json["model"] == "nomic-embed-text"
        assert json["input"] == ["revenue increased"]
        assert timeout == 3.0
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"embeddings": [native]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OllamaEmbeddingProvider(timeout_seconds=3, max_retries=0)

    vectors = provider.embed(["revenue increased"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 1536
    assert vectors[0][:768] == tuple(native)
    assert vectors[0][768:] == (0.0,) * 768


def test_ollama_rejects_wrong_native_dimension(monkeypatch):
    def fake_post(url, *, json, timeout):
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"embeddings": [[0.1, 0.2]]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OllamaEmbeddingProvider(
        config=EmbeddingModelConfig(
            provider="ollama",
            model_name="nomic-embed-text",
            model_version="test",
            dimensions=1536,
            native_dimensions=768,
        ),
        max_retries=0,
    )

    result = provider.embed_chunks(
        (),
        batch_size=1,
    )
    assert result == ()
