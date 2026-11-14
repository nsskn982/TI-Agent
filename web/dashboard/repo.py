"""Read-only access to the local PostgreSQL database for the website.

Every page reads through `Repo`, so tests can substitute a fake. The website
never writes to the database: it shows what the pipeline produced.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from functools import lru_cache

from django.core.cache import cache

log = logging.getLogger("dashboard")

CHUNK_ID = re.compile(r"^chunk_(\d+)$")


def chunk_ids(sources: list[str]) -> list[int]:
    return [int(m.group(1)) for s in sources or [] if (m := CHUNK_ID.match(s))]


def safe_url(url: str | None) -> str | None:
    """Only link out to http(s) URLs: a javascript: URL in data must never become a link."""
    return url if url and url.lower().startswith(("https://", "http://")) else None


class Repo:
    def __init__(self, store=None):
        if store is None:
            from common.store import Store

            store = Store()
        self.store = store

    # ------------------------------------------------------------ runs
    def agent_runs(self, limit: int = 20) -> list[dict]:
        return self.store.agent_runs(limit)

    def latest_good_run(self) -> dict | None:
        return self.store.latest_good_run()

    def ingestion_runs(self, limit: int = 40) -> list[dict]:
        return self.store.ingestion_runs(limit)

    # ------------------------------------------------------------ suggestions
    def suggestions_for_run(self, run_id: int) -> list[dict]:
        return self.store.suggestions_for_run(run_id)

    def ticker_suggestions(self, ticker: str, limit: int = 30) -> list[dict]:
        return self.store.ticker_suggestions(ticker, limit)

    def tickers(self) -> list[dict]:
        return self.store.tickers()

    # ------------------------------------------------------------ citations
    def chunks(self, ids: list[int]) -> dict[int, dict]:
        """{chunk_id: chunk + its document's title/url} for the given ids."""
        if not ids:
            return {}
        rows = self.store.get_chunks(ids)
        meta = self.store.get_document_meta(sorted({r["document_id"] for r in rows}))
        out = {}
        for r in rows:
            m = meta.get(r["document_id"], {})
            out[r["id"]] = {**r, "title": m.get("title"), "url": safe_url(m.get("url"))}
        return out

    # ------------------------------------------------------------ market data
    def price_history(self, ticker: str, days: int = 365) -> list[dict]:
        today = date.today()
        return self.store.get_prices(ticker, today - timedelta(days=days), today + timedelta(days=1))

    def features(self, ticker: str) -> dict:
        key = f"features:{ticker}:{date.today().isoformat()}"
        cached = cache.get(key)
        if cached is None:
            from quant.features import compute_features

            cached = compute_features(self.store, ticker, date.today())
            cache.set(key, cached)
        return cached


@lru_cache(maxsize=1)
def _default_repo() -> Repo:
    return Repo()


def get_repo() -> Repo:
    """Indirection point: tests monkeypatch this."""
    return _default_repo()
