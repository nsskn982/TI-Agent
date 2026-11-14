"""Incremental refresh: the first run backfills, later runs fetch only what is new.

Adjusted closes are re-based whenever a dividend or split happens. Incremental fetches
overlap the stored data by a week, and a ticker whose last stored adjusted close no longer
matches gets its full history again, so stored prices never go stale.
"""
from __future__ import annotations

from datetime import date, timedelta

OVERLAP_DAYS = 7          # re-fetch the last week (late corrections, rebase check)
STALE_DAYS = 30           # data older than this is re-fetched in full
FIRST_SLACK_DAYS = 14     # weekends/holidays at the start of the window
FILING_OVERLAP_DAYS = 30  # amended filings land a little after the original


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def price_since(mark: dict | None, full_since: date, today: date | None = None) -> date:
    """Start date for a ticker's price fetch: `full_since` for a backfill, else just before the last stored day."""
    today = today or date.today()
    if not mark:
        return full_since
    first, last = _d(mark["first"]), _d(mark["last"])
    if first > full_since + timedelta(days=FIRST_SLACK_DAYS) or last < today - timedelta(days=STALE_DAYS):
        return full_since
    return max(full_since, last - timedelta(days=OVERLAP_DAYS))


def rebased(mark: dict | None, rows: list[dict], tol: float = 1e-4) -> bool:
    """True if the fetched rows disagree with the last stored adjusted close (dividend/split)."""
    if not mark or mark.get("adj_close") is None:
        return False
    last = _d(mark["last"]).isoformat()
    row = next((r for r in rows if str(r.get("date"))[:10] == last), None)
    if row is None or row.get("adj_close") is None:
        return True  # no overlap to compare against: play safe
    old, new = float(mark["adj_close"]), float(row["adj_close"])
    return abs(new - old) > tol * max(abs(old), 1e-9)


def filed_since(mark: dict | None, full_since: date) -> date:
    """Start date for a fundamentals fetch: the full window on the first run, else the last filing - 30 days."""
    if not mark:
        return full_since
    first, last = _d(mark["first"]), _d(mark["last"])
    if first > full_since + timedelta(days=120):  # a filing a quarter: older history is missing
        return full_since
    return max(full_since, last - timedelta(days=FILING_OVERLAP_DAYS))


def marks(store, method: str, symbols: list[str]) -> dict[str, dict]:
    if store is None or not hasattr(store, method):
        return {}
    return getattr(store, method)(symbols)
