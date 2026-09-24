"""R-12-C 真实 Provider 的本地契约测试，不调用外部网络。"""

from types import SimpleNamespace

from tradingagents.rag.chunking import DocumentChunk
from tradingagents.rag.documents import DocumentChunkMetadata
from tradingagents.rag.embeddings import OpenAIEmbeddingProvider


def make_client(vectors, failures=0):
    state = {"calls": 0}

    class Embeddings:
        def create(self, **kwargs):
            state["calls"] += 1
            if state["calls"] <= failures:
                raise ConnectionError("simulated provider outage")
            data = [
                SimpleNamespace(index=index, embedding=vector)
                for index, vector in enumerate(vectors)
            ]
            return SimpleNamespace(data=data)

    return SimpleNamespace(embeddings=Embeddings()), state


def make_chunk(chunk_id: str, content: str) -> DocumentChunk:
    return DocumentChunk(
        metadata=DocumentChunkMetadata(
            chunk_id=chunk_id,
            document_id="aapl-2025q1",
            ordinal=0,
            section_title="Results",
            char_start=0,
            char_end=len(content),
            token_count=1,
        ),
        content=content,
    )


def vector(value: float) -> list[float]:
    return [value] + [0.001] * 1535


def test_provider_sends_one_request_per_batch_and_restores_index_order():
    fake, state = make_client([vector(0.1), vector(0.2)])
    provider = OpenAIEmbeddingProvider(client=fake, max_retries=0, backoff_seconds=0)

    results = provider.embed_chunks(
        (make_chunk("c1", "revenue"), make_chunk("c2", "margin")),
        batch_size=2,
    )

    assert state["calls"] == 1
    assert [item.status for item in results] == ["succeeded", "succeeded"]
    assert len(results[0].vector or ()) == 1536


def test_provider_retries_and_returns_retryable_failure_after_exhaustion():
    fake, state = make_client([vector(0.1)], failures=2)
    provider = OpenAIEmbeddingProvider(
        client=fake,
        max_retries=1,
        backoff_seconds=0,
    )

    result = provider.embed_chunks((make_chunk("c1", "revenue"),))[0]

    assert state["calls"] == 2
    assert result.status == "failed"
    assert result.retryable is True
    assert "simulated provider outage" in (result.error or "")
