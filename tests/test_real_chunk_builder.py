"""真实 Chunk 构建脚本的最小契约测试。"""

import json
from datetime import datetime, timezone

from scripts.build_real_chunks import build_all_chunks, process_manifest


def test_process_manifest_writes_chunk_jsonl(tmp_path):
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    raw_dir.mkdir()
    document_id = "demo-report"
    html = b"""<html><head><title>Demo Report</title></head><body>
    <h1>Financial Statements</h1><p>Revenue increased during the quarter.</p>
    <table><caption>Revenue by segment</caption><tr><th>Segment</th><th>Revenue</th></tr>
    <tr><td>Cloud</td><td>100 million</td></tr></table>
    </body></html>"""
    raw_path = raw_dir / f"{document_id}-abc.raw"
    manifest_path = raw_dir / f"{document_id}-abc.json"
    raw_path.write_bytes(html)
    manifest_path.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "document_id": document_id,
                "content_type": "text/html",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "document_id": document_id,
                    "ticker": "AAPL",
                    "document_type": "quarterly_report",
                    "title": "Demo Report",
                    "source_url": "https://example.com/demo.html",
                    "source_hash": __import__("hashlib").sha256(html).hexdigest(),
                    "published_at": "2025-01-01",
                    "available_at": "2025-01-01",
                    "language": "en",
                },
            }
        ),
        encoding="utf-8",
    )

    summary = process_manifest(manifest_path, output_dir, target_tokens=5, max_tokens=20)

    chunks_path = output_dir / f"{document_id}.chunks.jsonl"
    records = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
    assert summary["chunk_count"] == len(records)
    assert summary["table_blocks"] == 1
    assert records[0]["document"]["ticker"] == "AAPL"
    assert all(record["chunk"]["metadata"]["token_count"] <= 20 for record in records)


def test_build_all_chunks_can_filter_by_ticker(tmp_path):
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    raw_dir.mkdir()

    for document_id, ticker in (("aapl-report", "AAPL"), ("tsla-report", "TSLA")):
        html = f"<html><body><h1>{ticker} Report</h1><p>Revenue increased.</p></body></html>".encode()
        stem = raw_dir / document_id
        stem.with_suffix(".raw").write_bytes(html)
        stem.with_suffix(".json").write_text(
            json.dumps(
                {
                    "status": "succeeded",
                    "document_id": document_id,
                    "content_type": "text/html",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "metadata": {
                        "document_id": document_id,
                        "ticker": ticker,
                        "document_type": "annual_report",
                        "title": f"{ticker} Report",
                        "source_url": f"https://example.com/{document_id}.html",
                        "source_hash": __import__("hashlib").sha256(html).hexdigest(),
                        "published_at": "2025-01-01",
                        "available_at": "2025-01-01",
                        "language": "en",
                    },
                }
            ),
            encoding="utf-8",
        )

    summaries = build_all_chunks(raw_dir, output_dir, ticker="TSLA")

    assert [item["ticker"] for item in summaries] == ["TSLA"]
    assert (output_dir / "tsla-report.chunks.jsonl").exists()
    assert not (output_dir / "aapl-report.chunks.jsonl").exists()
