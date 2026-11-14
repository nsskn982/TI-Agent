from ingestion import run as ingest_run
from processing import run as process_run
from tests.fakes import FakeEmbedder, FakeStore


def _patch_sources(monkeypatch, fail_prices_for=()):
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setenv("FRED_API_KEY", "k")
    monkeypatch.setattr(ingest_run.edgar, "load_cik_map", lambda s: {"AAPL": {"cik": 320193, "name": "Apple Inc."}})

    def fake_prices(t, since):
        if t in fail_prices_for:
            raise RuntimeError("boom")
        return [{"ticker": t, "date": "2024-11-08", "open": 1, "high": 1, "low": 1, "close": 1,
                 "adj_close": 1, "volume": 1}]

    monkeypatch.setattr(ingest_run.prices, "fetch_prices", fake_prices)
    monkeypatch.setattr(ingest_run.finnhub, "fetch_company_news", lambda s, t, a, b, k: [
        {"id": 7, "headline": f"{t} news", "summary": "Something happened.", "datetime": 1731283200}])
    monkeypatch.setattr(ingest_run.edgar, "fetch_filings", lambda s, t, cik, since, mc, skip_ids=None: [
        {"ticker": t, "source": "filing", "source_id": "edgar:1", "doc_type": "10-K", "title": "10-K",
         "url": "u", "published_at": "2024-11-01T18:00:00+00:00",
         "body": " ".join(f"Sentence {i} of the annual report." for i in range(200)), "meta": {}}])
    monkeypatch.setattr(ingest_run.fundamentals, "fetch_fundamentals", lambda s, t, cik, since: [
        {"ticker": t, "concept": "us-gaap:Revenues", "unit": "USD", "period_start": "2026-07-01",
         "period_end": "2026-09-30", "value": 1e9, "form": "10-Q", "fp": "Q3", "fy": 2026,
         "filed": "2026-10-30", "accn": "x"}])
    monkeypatch.setattr(ingest_run.fred, "fetch_series", lambda s, sid, start, key: [
        {"series_id": sid, "date": "2024-11-08", "value": 1.0}])


def test_ingest_then_process_end_to_end(monkeypatch):
    _patch_sources(monkeypatch)
    store = FakeStore()
    run = ingest_run.ingest(["AAPL", "SPY"], days=5, sources=ingest_run.SOURCES, store=store)

    assert run.errors == []
    assert store.tickers["AAPL"]["cik"] == 320193 and store.tickers["SPY"]["cik"] is None
    assert len(store.prices) == 2 and len(store.macro) == len(ingest_run.fred.DEFAULT_SERIES)
    # SPY has no CIK -> news only; AAPL -> news + filing.
    assert sorted((d["ticker"], d["source"]) for d in store.documents.values()) == [
        ("AAPL", "filing"), ("AAPL", "news"), ("SPY", "news")]

    # Re-ingesting does not duplicate documents.
    ingest_run.ingest(["AAPL", "SPY"], days=5, sources=ingest_run.SOURCES, store=store)
    assert len(store.documents) == 3

    emb = FakeEmbedder()
    stats = process_run.process(store, emb)
    assert stats["documents"] == 3 and stats["failed"] == 0
    assert all(d["processed_at"] for d in store.documents.values())

    filing_id = next(i for i, d in store.documents.items() if d["source"] == "filing")
    chunks = store.chunks[filing_id]
    assert len(chunks) > 1
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert all(len(c["embedding"]) == 384 for c in chunks)
    assert all(c["published_at"] == "2024-11-01T18:00:00+00:00" for c in chunks)
    # Embedded text carries a ticker/form header; stored content does not.
    embedded = [t for call in emb.calls for t in call]
    assert any(t.startswith("AAPL 10-K: Sentence 0") for t in embedded)
    assert not chunks[0]["content"].startswith("AAPL 10-K")

    # Nothing left to do on a second pass.
    assert process_run.process(store, emb)["documents"] == 0


def test_ingest_isolates_failures(monkeypatch):
    _patch_sources(monkeypatch, fail_prices_for=("SPY",))
    store = FakeStore()
    run = ingest_run.ingest(["AAPL", "SPY"], days=5, sources=("prices",), store=store)
    assert [(e["source"], e["key"]) for e in run.errors] == [("prices", "SPY")]
    assert ("AAPL", "2024-11-08") in store.prices


def test_missing_key_is_reported(monkeypatch):
    _patch_sources(monkeypatch)
    monkeypatch.delenv("FINNHUB_API_KEY")
    store = FakeStore()
    run = ingest_run.ingest(["AAPL"], days=5, sources=("news",), store=store)
    assert run.errors and run.errors[0]["source"] == "news"


def test_process_flags_failing_document(monkeypatch):
    store = FakeStore()
    store.insert_documents([{"ticker": "AAPL", "source": "news", "source_id": "a", "title": "t", "body": "b",
                             "published_at": "2024-11-01T00:00:00+00:00"}])

    class Broken:
        def encode(self, texts):
            raise RuntimeError("gpu on fire")

    stats = process_run.process(store, Broken())
    assert stats["failed"] == 1 and stats["documents"] == 0
    assert "gpu on fire" in store.documents[1]["process_error"]
    assert process_run.process(store, Broken())["failed"] == 0  # not retried forever


def test_watchlist_parsing(monkeypatch):
    monkeypatch.setenv("WATCHLIST", "aapl, msft,AAPL,, # comment")
    assert ingest_run.load_watchlist(None) == ["AAPL", "MSFT"]
    assert ingest_run.load_watchlist(["nvda"]) == ["NVDA"]


def test_benchmark_prices_always_fetched(monkeypatch):
    _patch_sources(monkeypatch)
    store = FakeStore()
    run = ingest_run.ingest(["AAPL"], days=5, sources=("prices", "fundamentals"), store=store)
    assert run.errors == []
    assert {t for t, _ in store.prices} == {"AAPL", "SPY"}
    assert store.tickers["SPY"]["active"] is False and store.tickers["AAPL"]["active"] is True
    assert len(store.fundamentals) == 1


def test_out_of_memory_stops_processing_without_marking_failed():
    import pytest
    from processing import run as proc_run
    from tests.fakes import FakeStore

    class OOMEmbedder:
        def encode(self, texts):
            raise OSError(22, "The paging file is too small for this operation to complete")

    store = FakeStore()
    store.insert_documents([{"ticker": "AAPL", "source": "news", "source_id": "x", "title": "t", "body": "b",
                             "published_at": "2026-11-10T00:00:00+00:00"}])
    with pytest.raises(OSError):
        proc_run.process(store, OOMEmbedder())
    assert all(d["process_error"] is None for d in store.documents.values())
