"""The S&P 500 universe and the weekly "focus" set (the top-N picks the agent analyses).

Constituents come from Wikipedia's "List of S&P 500 companies" table (free, updated when the
index changes). Symbols are stored in Yahoo/SEC form, e.g. BRK-B; Finnhub wants BRK.B.

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
# Wikipedia asks automated clients for a descriptive User-Agent.
WIKI_HEADERS = {"User-Agent": "TI-Agent/1.0 (research project; github.com/nsskn982/TI-Agent)"}


def to_storage_symbol(symbol: str) -> str:
    """BRK.B -> BRK-B (the form yfinance and SEC's ticker map use)."""
    return symbol.strip().upper().replace(".", "-")


def to_finnhub_symbol(symbol: str) -> str:
    """BRK-B -> BRK.B."""
    return symbol.replace("-", ".")


def parse_constituents(html: str) -> list[dict]:
    """Rows from the constituents table: symbol, name, sector, cik."""
    tables = pd.read_html(io.StringIO(html))
    table = next((t for t in tables if {"Symbol", "Security"}.issubset(set(map(str, t.columns)))), None)
    if table is None:
        raise ValueError("S&P 500 constituents table not found on the page")
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
    if len(out) < 400:  # the index has ~503 lines; far fewer means the page layout changed
        raise ValueError(f"only {len(out)} constituents parsed; page layout may have changed")
    return out


def fetch_sp500(session: requests.Session | None = None) -> list[dict]:
    s = session or requests.Session()
    resp = s.get(WIKI_URL, headers=WIKI_HEADERS, timeout=30)
    resp.raise_for_status()
    return parse_constituents(resp.text)


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
