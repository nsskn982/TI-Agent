"""M1 ingestion entry point.

    python -m ingestion.run --tickers AAPL MSFT
    python -m ingestion.run --days 730            # first-time backfill
    python -m ingestion.run --sources prices macro --dry-run

Each source/ticker is isolated: one failure is logged and the rest continue.
Exit code is 1 if anything failed, so the GitHub Action shows red.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from common import logging_setup
from common.config import ROOT, benchmark, env, env_int, require
from common.http import make_session
from ingestion import edgar, finnhub, fred, fundamentals, prices

log = logging.getLogger("ingestion")

SOURCES = ("prices", "news", "filings", "fundamentals", "macro")

# Adjusted closes are re-based whenever a dividend/split happens, so stored
# history is refreshed in full each run instead of appending only new days.
PRICE_HISTORY_DAYS = 800
# A TTM figure a year ago needs facts filed up to ~2 years before the window.
FUNDAMENTALS_EXTRA_DAYS = 760



def load_watchlist(cli: list[str] | None) -> list[str]:
    if cli:
        raw = cli
    elif env("WATCHLIST"):
        raw = env("WATCHLIST", "").split(",")
    else:
        path = ROOT / "watchlist.txt"
        raw = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen, out = set(), []
    for t in raw:
        t = t.split("#", 1)[0].strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


class Run:
    def __init__(self, store, dry_run: bool):
        self.store = store
        self.dry_run = dry_run
        self.counts: Counter = Counter()
        self.errors: list[dict] = []

    def write(self, kind: str, method: str, rows: list[dict]) -> None:
        self.counts[kind] += len(rows)
        if self.dry_run or not rows:
            return
        getattr(self.store, method)(rows)

    def fail(self, source: str, key: str, exc: Exception) -> None:
        log.error("%s %s failed: %s", source, key, exc)
        self.errors.append({"source": source, "key": key, "error": f"{type(exc).__name__}: {exc}"[:500]})


def ingest(tickers: list[str], days: int, sources: tuple[str, ...], store, dry_run: bool = False) -> Run:
    run = Run(store, dry_run)
    today = date.today()
    since = today - timedelta(days=days)

    edgar_session = None
    cik_map: dict[str, dict] = {}
    # The EDGAR ticker map also gives us company names/CIKs for the tickers table.
    needs_edgar = "filings" in sources or "fundamentals" in sources
    if needs_edgar or not dry_run:
        try:
            edgar_session = make_session(require("SEC_USER_AGENT"))
            cik_map = edgar.load_cik_map(edgar_session)
        except Exception as exc:
            edgar_session = None
            if needs_edgar:
                run.fail("edgar", "ticker_map", exc)
            else:
                log.warning("EDGAR ticker map unavailable (%s); ticker names left blank", exc)

    # Tickers must exist before rows referencing them.
    # Without the CIK map, don't overwrite previously stored names/CIKs with nulls.
    # The benchmark (SPY) gets prices only, for beta/relative strength and M10 scoring.
    bench = benchmark()
    price_tickers = tickers + ([bench] if bench not in tickers else [])
    ticker_rows = [
        {"symbol": t, "active": t in tickers}
        | ({"name": cik_map.get(t, {}).get("name"), "cik": cik_map.get(t, {}).get("cik")} if cik_map else {})
        for t in price_tickers
    ]
    if not dry_run:
        store.upsert_tickers(ticker_rows)

    if "prices" in sources:
        price_since = today - timedelta(days=max(days, PRICE_HISTORY_DAYS))
        for t in price_tickers:
            try:
                rows = prices.fetch_prices(t, price_since)
                if not rows:
                    raise ValueError("no price rows returned")
                run.write("prices", "upsert_prices", rows)
            except Exception as exc:
                run.fail("prices", t, exc)

    if "news" in sources:
        session = make_session()
        try:
            token = require("FINNHUB_API_KEY")
        except Exception as exc:
            run.fail("news", "config", exc)
        else:
            # Finnhub free tier only serves ~1 year of company news.
            news_since = max(since, today - timedelta(days=365))
            for t in tickers:
                try:
                    items = finnhub.fetch_company_news(session, t, news_since, today, token)
                    run.write("news", "insert_documents", finnhub.to_documents(t, items))
                except Exception as exc:
                    run.fail("news", t, exc)

    if "filings" in sources and edgar_session is not None:
        max_chars = env_int("MAX_FILING_CHARS", 300_000)
        for t in tickers:
            info = cik_map.get(t)
            if info is None:
                log.warning("No CIK for %s (ETF or foreign issuer?) - skipping filings", t)
                continue
            try:
                skip = set() if dry_run else store.existing_source_ids(t, "filing")
                docs = edgar.fetch_filings(edgar_session, t, info["cik"], since, max_chars, skip_ids=skip)
                run.write("filings", "insert_documents", docs)
            except Exception as exc:
                run.fail("filings", t, exc)

    if "fundamentals" in sources and edgar_session is not None:
        filed_since = since - timedelta(days=FUNDAMENTALS_EXTRA_DAYS)
        for t in tickers:
            info = cik_map.get(t)
            if info is None:
                continue
            try:
                rows = fundamentals.fetch_fundamentals(edgar_session, t, info["cik"], filed_since)
                run.write("fundamentals", "upsert_fundamentals", rows)
            except Exception as exc:
                run.fail("fundamentals", t, exc)

    if "macro" in sources:
        session = make_session()
        try:
            key = require("FRED_API_KEY")
        except Exception as exc:
            run.fail("macro", "config", exc)
        else:
            # Monthly series need a longer window to always capture the latest print.
            macro_since = min(since, today - timedelta(days=120))
            for series in fred.DEFAULT_SERIES:
                try:
                    run.write("macro", "upsert_macro", fred.fetch_series(session, series, macro_since, key))
                except Exception as exc:
                    run.fail("macro", series, exc)

    return run


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description="TI Agent ingestion (M1)")
    p.add_argument("--tickers", nargs="*", help="Override watchlist")
    p.add_argument("--days", type=int, default=5, help="Lookback window in days (use ~730 for backfill)")
    p.add_argument("--sources", nargs="*", choices=SOURCES, default=list(SOURCES))
    p.add_argument("--dry-run", action="store_true", help="Fetch but do not write to Supabase")
    args = p.parse_args(argv)

    started = datetime.now(timezone.utc)
    store = None
    if not args.dry_run:
        from common.store import Store

        store = Store()

    # Default: the latest S&P 500 screen's picks (orchestration/screen_run.py); watchlist.txt
    # until the first screen has run. --tickers or WATCHLIST still override.
    tickers = load_watchlist(args.tickers)
    if not args.tickers and not env("WATCHLIST"):
        from ingestion.universe import focus_tickers

        tickers = focus_tickers(store, tickers)
    if not tickers:
        log.error("Empty watchlist: pass --tickers or fill watchlist.txt")
        return 2

    log.info("Ingesting %s for %s (last %d days)", ",".join(args.sources), ",".join(tickers), args.days)
    run = ingest(tickers, args.days, tuple(args.sources), store, args.dry_run)

    status = "ok" if not run.errors else ("error" if not sum(run.counts.values()) else "partial")
    log.info("Done: status=%s counts=%s errors=%d", status, dict(run.counts), len(run.errors))
    if store is not None:
        store.log_run(
            {
                "job": "ingestion",
                "started_at": started.isoformat(),
                "status": status,
                "counts": dict(run.counts),
                "errors": run.errors,
            }
        )
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
