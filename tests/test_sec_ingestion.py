"""R-14-B SEC 批量下载测试；所有网络行为均使用内存 Mock。"""

import json
from datetime import date, datetime, timezone

from tradingagents.rag.ingestion import FetchedDocument
from tradingagents.rag.sec_filings import SECFilingCandidate
from tradingagents.rag.sec_ingestion import (
    SECIngestionError,
    ingest_sec_candidates,
    ingest_sec_discovery_file,
)
from tradingagents.rag.storage import LocalObjectStorage


def make_candidate(
    document_id: str,
    *,
    filing_date: date = date(2025, 1, 29),
    url: str | None = None,
) -> SECFilingCandidate:
    return SECFilingCandidate(
        document_id=document_id,
        ticker="TSLA",
        cik=1318605,
        company_name="Tesla, Inc.",
        form="10-K",
        document_type="annual_report",
        accession_number="0001318605-25-000001",
        filing_date=filing_date,
        report_date=date(2024, 12, 31),
        available_at=filing_date,
        fiscal_period="FY2024-FY",
        primary_document="tsla-20241231.htm",
        source_url=url or f"https://www.sec.gov/{document_id}.htm",
    )


def make_fetcher(content_by_url: dict[str, bytes], calls: list[dict]):
    def fetcher(url, **kwargs):
        calls.append({"url": url, **kwargs})
        content = content_by_url[url]
        return FetchedDocument(
            source_url=url,
            content=content,
            content_type="text/html",
            fetched_at=datetime.now(timezone.utc),
        )

    return fetcher


def test_batch_download_writes_raw_manifest_and_passes_sec_user_agent(tmp_path):
    candidate = make_candidate("sec-tsla-10-k-2025")
    calls: list[dict] = []
    summary = ingest_sec_candidates(
        [candidate],
        output_dir=tmp_path,
        as_of=date(2025, 3, 1),
        user_agent="TradeAgent/test (test@example.com)",
        fetcher=make_fetcher({candidate.source_url: b"<html>10-K</html>"}, calls),
    )

    assert summary.stored_count == 1
    assert summary.failed_count == 0
    assert calls[0]["user_agent"] == "TradeAgent/test (test@example.com)"
    raw_files = list(tmp_path.glob("*.raw"))
    manifests = list(tmp_path.glob("*.json"))
    assert len(raw_files) == len(manifests) == 1
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["published_at"] == "2025-01-29"
    assert payload["metadata"]["period_end"] == "2024-12-31"
    assert payload["metadata"]["document_type"] == "annual_report"


def test_existing_success_manifest_is_skipped_without_network(tmp_path):
    candidate = make_candidate("sec-tsla-existing")
    calls: list[dict] = []
    fetcher = make_fetcher({candidate.source_url: b"same"}, calls)
    first = ingest_sec_candidates(
        [candidate], output_dir=tmp_path, as_of=date(2025, 3, 1), fetcher=fetcher
    )
    second = ingest_sec_candidates(
        [candidate], output_dir=tmp_path, as_of=date(2025, 3, 1), fetcher=fetcher
    )

    assert first.stored_count == 1
    assert second.skipped_count == 1
    assert len(calls) == 1


def test_one_failure_does_not_stop_remaining_candidates(tmp_path):
    good = make_candidate("sec-tsla-good", url="https://example.com/good")
    bad = make_candidate("sec-tsla-bad", url="https://example.com/bad")
    calls: list[dict] = []

    def fetcher(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if url.endswith("bad"):
            raise TimeoutError("upstream timeout")
        return FetchedDocument(
            source_url=url,
            content=b"good",
            content_type="text/html",
            fetched_at=datetime.now(timezone.utc),
        )

    summary = ingest_sec_candidates(
        [bad, good], output_dir=tmp_path, as_of=date(2025, 3, 1), fetcher=fetcher
    )

    assert summary.stored_count == 1
    assert summary.failed_count == 1
    failed = list(tmp_path.glob("failed-*.json"))
    assert len(failed) == 1
    assert "upstream timeout" in failed[0].read_text(encoding="utf-8")


def test_future_candidate_is_filtered_without_network(tmp_path):
    candidate = make_candidate("sec-tsla-future", filing_date=date(2026, 1, 1))
    calls: list[dict] = []
    summary = ingest_sec_candidates(
        [candidate],
        output_dir=tmp_path,
        as_of=date(2025, 3, 1),
        fetcher=make_fetcher({candidate.source_url: b"future"}, calls),
    )

    assert summary.filtered_future_count == 1
    assert summary.stored_count == 0
    assert calls == []


def test_discovery_file_is_validated_and_summary_keeps_input_path(tmp_path):
    candidate = make_candidate("sec-tsla-file")
    input_path = tmp_path / "discovery.json"
    input_path.write_text(
        json.dumps({"as_of": "2025-03-01", "filings": [candidate.model_dump(mode="json")] }),
        encoding="utf-8",
    )
    summary = ingest_sec_discovery_file(
        input_path,
        output_dir=tmp_path / "raw",
        fetcher=make_fetcher({candidate.source_url: b"file"}, []),
    )

    assert summary.input_path == str(input_path)
    assert summary.total_candidates == 1


def test_invalid_discovery_file_is_rejected(tmp_path):
    input_path = tmp_path / "invalid.json"
    input_path.write_text(json.dumps({"filings": [{"document_id": "bad"}]}), encoding="utf-8")

    try:
        ingest_sec_discovery_file(input_path, output_dir=tmp_path / "raw")
    except SECIngestionError as exc:
        assert "invalid SEC candidate" in str(exc)
    else:
        raise AssertionError("invalid discovery input should be rejected")


def test_batch_download_can_write_the_same_immutable_object_to_object_storage(tmp_path):
    candidate = make_candidate("sec-tsla-object")
    object_storage = LocalObjectStorage(tmp_path / "objects")
    summary = ingest_sec_candidates(
        [candidate],
        output_dir=tmp_path / "raw",
        as_of=date(2025, 3, 1),
        fetcher=make_fetcher({candidate.source_url: b"object-bytes"}, []),
        object_storage=object_storage,
    )

    item = summary.items[0]
    assert item["object_bucket"] == "financial-raw"
    assert item["object_key"].endswith(".source")
    assert object_storage.get(item["object_bucket"], item["object_key"], version=item["object_version"]) == b"object-bytes"
