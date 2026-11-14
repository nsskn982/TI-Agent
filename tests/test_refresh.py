"""Incremental refresh: backfill once, then fetch only new days (and re-fetch on a rebase)."""
from datetime import date

import ingestion.run as ingest_run
from ingestion import refresh
from tests.fakes import FakeStore

TODAY = date(2026, 11, 14)
FULL = date(2024, 9, 5)


def test_price_since_backfills_then_goes_incremental():
    assert refresh.price_since(None, FULL, TODAY) == FULL
    mark = {"first": "2024-09-06", "last": "2026-11-13", "adj_close": 10.0}
    assert refresh.price_since(mark, FULL, TODAY) == date(2026, 11, 6)
    # history too short (ticker added with a few days only) or stale -> full backfill
    assert refresh.price_since({**mark, "first": "2026-11-01"}, FULL, TODAY) == FULL
    assert refresh.price_since({**mark, "last": "2026-09-01"}, FULL, TODAY) == FULL


def test_rebased_detects_changed_adjusted_close():
    mark = {"first": "2024-09-06", "last": "2026-11-13", "adj_close": 100.0}
    same = [{"date": "2026-11-13", "adj_close": 100.0}, {"date": "2026-11-14", "adj_close": 101.0}]
    moved = [{"date": "2026-11-13", "adj_close": 99.2}]
    assert not refresh.rebased(mark, same)
    assert refresh.rebased(mark, moved)
    assert refresh.rebased(mark, [])          # no overlap: play safe
    assert not refresh.rebased(None, moved)   # nothing stored yet


def test_filed_since():
    assert refresh.filed_since(None, FULL) == FULL
    assert refresh.filed_since({"first": "2024-10-01", "last": "2026-10-30"}, FULL) == date(2026, 9, 30)
    assert refresh.filed_since({"first": "2026-01-01", "last": "2026-10-30"}, FULL) == FULL


def test_second_ingest_fetches_only_recent_prices(monkeypatch):
    calls = []

    def fake_prices(t, since, end=None):
        calls.append((t, since))
        return [{"ticker": t, "date": d, "close": 1.0, "adj_close": 1.0} for d in ("2024-09-06", "2026-11-13")
                if d >= since.isoformat()]

    monkeypatch.setattr(ingest_run.prices, "fetch_prices", fake_prices)
    monkeypatch.setattr(ingest_run, "date", type("D", (date,), {"today": staticmethod(lambda: TODAY)}))
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    monkeypatch.setattr(ingest_run.edgar, "load_cik_map", lambda s: {})
    store = FakeStore()
    ingest_run.ingest(["AAPL"], days=5, sources=("prices",), store=store)
    first = dict(calls)
    calls.clear()
    ingest_run.ingest(["AAPL"], days=5, sources=("prices",), store=store)
    assert calls and all(since > first[t] for t, since in calls)
    assert all(since == date(2026, 11, 6) for _, since in calls)
