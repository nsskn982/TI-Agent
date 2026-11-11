"""The screening universe (S&P 500 large caps + S&P MidCap 400) and the weekly "focus" set
(the top-N picks the agent analyses).

Constituents come from Wikipedia's "List of S&P 500 companies" / "List of S&P 400 companies"
tables (free, updated when the indexes change). Symbols are stored in Yahoo/SEC form, e.g.
BRK-B; Finnhub wants BRK.B. The S&P 400 table has no CIK column; the screen gets CIKs from
SEC's ticker map instead.

Known limitation: this is *today's* membership. Backtesting on it has survivorship bias
(companies that fell out of the index are missing). Fine for a forward-looking weekly screen.
"""
from __future__ import annotations

import io
import logging

import pandas as pd
import requests

log = logging.getLogger(__name__)

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# index name -> (Wikipedia page, minimum rows expected; far fewer means the page layout changed)
INDEXES = {
    "S&P 500": (WIKI_URL, 400),
    "S&P 400": ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", 330),
}
# Wikipedia asks automated clients for a descriptive User-Agent.
WIKI_HEADERS = {"User-Agent": "TI-Agent/1.0 (research project; github.com/nsskn982/TI-Agent)"}


def to_storage_symbol(symbol: str) -> str:
    """BRK.B -> BRK-B (the form yfinance and SEC's ticker map use)."""
    return symbol.strip().upper().replace(".", "-")


def to_finnhub_symbol(symbol: str) -> str:
    """BRK-B -> BRK.B."""
    return symbol.replace("-", ".")


def parse_constituents(html: str, min_rows: int = 400) -> list[dict]:
    """Rows from the constituents table: symbol, name, sector, cik (None if the table has none)."""
    tables = pd.read_html(io.StringIO(html))
    table = next((t for t in tables if {"Symbol", "Security"}.issubset(set(map(str, t.columns)))), None)
    if table is None:
        raise ValueError("constituents table not found on the page")
    out, seen = [], set()
    for _, r in table.iterrows():
        sym = to_storage_symbol(str(r["Symbol"]))
        if not sym or sym in seen:
            continue
        seen.add(sym)
        cik = r.get("CIK")
        try:
            cik = int(cik) if pd.notna(cik) else None
        except (TypeError, ValueError):
            cik = None
        out.append({
            "symbol": sym,
            "name": str(r["Security"]).strip() or None,
            "sector": str(r.get("GICS Sector", "")).strip() or None,
            "cik": cik,
        })
    if len(out) < min_rows:
        raise ValueError(f"only {len(out)} constituents parsed; page layout may have changed")
    return out


def fetch_index(name: str, session: requests.Session | None = None) -> list[dict]:
    url, min_rows = INDEXES[name]
    s = session or requests.Session()
    resp = s.get(url, headers=WIKI_HEADERS, timeout=30)
    resp.raise_for_status()
    return [{**r, "index": name} for r in parse_constituents(resp.text, min_rows)]


def fetch_sp500(session: requests.Session | None = None) -> list[dict]:
    return fetch_index("S&P 500", session)


def fetch_universe(session: requests.Session | None = None) -> list[dict]:
    """S&P 500 + S&P 400 constituents, each tagged with its `index`. A symbol listed in both
    (only briefly, around index changes) keeps its S&P 500 entry."""
    out: dict[str, dict] = {}
    for name in INDEXES:
        for r in fetch_index(name, session):
            out.setdefault(r["symbol"], r)
    return list(out.values())


def focus_tickers(store, fallback: list[str]) -> list[str]:
    """Tickers the expensive pipeline works on: the latest screen's selected picks, best first.
    Falls back to the watchlist when no screen has run yet (or there is no store)."""
    if store is None or not hasattr(store, "latest_selected"):
        return fallback
    try:
        picks = store.latest_selected()
    except Exception as exc:  # a missing screens table shouldn't stop ingestion
        log.warning("No screen available (%s); using the watchlist", exc)
        return fallback
    return picks or fallback
