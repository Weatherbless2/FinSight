import json
from datetime import date

from scripts.bootstrap_opensearch import iter_projections, load_projection


class FakeClient:
    def __init__(self):
        self.created = []
        self.batches = []

    def create_index(self, index, *, index_version):
        self.created.append((index, index_version))

    def bulk_upsert(self, index, documents):
        self.batches.append((index, documents))


def test_processed_chunks_become_rebuildable_projections(tmp_path):
    path = tmp_path / "chunks.jsonl"
    path.write_text(
        json.dumps(
            {
                "document": {
                    "document_id": "aapl-2024-10k",
                    "ticker": "AAPL",
                    "document_type": "annual_report",
                    "published_at": "2024-11-01",
                },
                "chunk": {
                    "metadata": {"chunk_id": "chunk-1", "section_title": "Risk"},
                    "content": "Risk content",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    projection = next(iter_projections([path], tenant_id="research"))
    assert projection["chunk_id"] == "chunk-1"
    assert projection["published_at"] == date(2024, 11, 1).isoformat()
    assert projection["available_at"] == date(2024, 11, 1).isoformat()
    assert projection["tenant_id"] == "research"

    client = FakeClient()
    assert load_projection(client, "rag-v1", [path], tenant_id="research", batch_size=1) == 1
    assert client.created == [("rag-v1", "rag-v1")]
    assert len(client.batches) == 1
