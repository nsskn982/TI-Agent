"""Weekly S&P 500 screen (runs in GitHub Actions on Friday night, before the weekly agent run).

    python -m orchestration.screen_run                    # refresh universe + data, screen, backfill picks
    python -m orchestration.screen_run --skip-refresh     # re-screen from data already in Supabase
    python -m orchestration.screen_run --top-n 20 --as-of 2026-11-14

Steps:
  1. S&P 500 constituents (Wikipedia) -> tickers (in_sp500, sector, CIK)
  2. ~800 days of prices for every constituent + the benchmark (batched yfinance download)
  3. SEC XBRL fundamentals for every constituent
  4. screen: momentum among quality companies -> `screens`, top N marked `selected`
  5. picks with no documents yet get a news + filings backfill, then chunk/embed/sentiment

The daily ingest and the weekly agent run then work on the selected picks only.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from common import logging_setup
from common.config import benchmark, env_int, require
from common.http import make_session
from ingestion import edgar, fundamentals, prices, universe
from ingestion.run import FUNDAMENTALS_EXTRA_DAYS, PRICE_HISTORY_DAYS
from quant.screen import run_screen

log = logging.getLogger("screen")

BACKFILL_DAYS = 730


def refresh_universe(store, counts: Counter, errors: list) -> tuple[list[str], dict[str, str], dict[str, int]]:
    """Upsert constituents; returns (symbols, sector by symbol, cik by symbol)."""
    try:
        members = universe.fetch_sp500()
    except Exception as exc:
        errors.append({"source": "universe", "key": "wikipedia", "error": f"{type(exc).__name__}: {exc}"[:500]})
        log.error("Could not fetch S&P 500 list (%s); using the stored universe", exc)
        syms = store.sp500_symbols()
        return syms, {}, {}
    current = {m["symbol"] for m in members}
    dropped = [s for s in store.sp500_symbols() if s not in current]
    rows = [{"symbol": m["symbol"], "name": m["name"], "sector": m["sector"], "cik": m["cik"], "in_sp500": True}
            for m in members]
    rows += [{"symbol": s, "in_sp500": False} for s in dropped]
    store.upsert_tickers(rows)
    counts["universe"] = len(members)
    if dropped:
        log.info("Left the index since last run: %s", ", ".join(dropped))
    return ([m["symbol"] for m in members], {m["symbol"]: m["sector"] for m in members},
            {m["symbol"]: m["cik"] for m in members if m["cik"]})


def refresh_data(store, symbols: list[str], ciks: dict[str, int], counts: Counter, errors: list) -> None:
    today = date.today()
    bench = benchmark()
    store.upsert_tickers([{"symbol": bench}])
    got = prices.fetch_many(symbols + [bench], today - timedelta(days=PRICE_HISTORY_DAYS))
    for s in symbols + [bench]:
        rows = got.get(s)
        if not rows:
            errors.append({"source": "prices", "key": s, "error": "no price rows"})
            continue
        store.upsert_prices(rows)
        counts["prices"] += len(rows)

    session = make_session(require("SEC_USER_AGENT"))
    try:
        sec_map = edgar.load_cik_map(session)
    except Exception as exc:
        sec_map = {}
        log.warning("SEC ticker map unavailable (%s); using Wikipedia CIKs", exc)
    filed_since = today - timedelta(days=BACKFILL_DAYS + FUNDAMENTALS_EXTRA_DAYS)
    for s in symbols:
        cik = (sec_map.get(s) or {}).get("cik") or ciks.get(s)
        if not cik:
            errors.append({"source": "fundamentals", "key": s, "error": "no CIK"})
            continue
        try:
            rows = fundamentals.fetch_fundamentals(session, s, cik, filed_since)
            store.upsert_fundamentals(rows)
            counts["fundamentals"] += len(rows)
        except Exception as exc:
            errors.append({"source": "fundamentals", "key": s, "error": f"{type(exc).__name__}: {exc}"[:300]})


def backfill_picks(store, picks: list[str], counts: Counter, errors: list) -> None:
    """New picks have no news/filings yet: fetch two years, then embed them."""
    from ingestion.run import ingest

    newcomers = [t for t in picks if not store.has_documents(t)]
    counts["new_picks"] = len(newcomers)
    if not newcomers:
        return
    log.info("Backfilling news and filings for new picks: %s", ", ".join(newcomers))
    run = ingest(newcomers, BACKFILL_DAYS, ("news", "filings"), store)
    counts.update({f"backfill_{k}": v for k, v in run.counts.items()})
    errors.extend(run.errors)

    from processing.embed import Embedder
    from processing.run import process, score_sentiment
    from processing.sentiment import SentimentScorer

    stats = process(store, Embedder())
    counts["chunked_docs"], counts["chunks"] = stats["documents"], stats["chunks"]
    errors.extend({"source": "processing", **e} for e in stats["errors"][:50])
    try:
        counts["scored_news"] = score_sentiment(store, SentimentScorer())
    except Exception as exc:
        errors.append({"source": "sentiment", "key": "finbert", "error": f"{type(exc).__name__}: {exc}"[:300]})


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description="Weekly S&P 500 screen")
    p.add_argument("--as-of", type=date.fromisoformat, default=None, help="Screen date (default: tomorrow, "
                   "so the latest close counts)")
    p.add_argument("--top-n", type=int, default=env_int("SCREEN_TOP_N", 20))
    p.add_argument("--skip-refresh", action="store_true", help="Don't download; screen stored data")
    p.add_argument("--no-backfill", action="store_true")
    args = p.parse_args(argv)

    from common.store import Store

    store = Store()
    started = datetime.now(timezone.utc)
    counts: Counter = Counter()
    errors: list[dict] = []

    if args.skip_refresh:
        symbols, sectors = store.sp500_symbols(), {}
    else:
        symbols, sectors, ciks = refresh_universe(store, counts, errors)
        refresh_data(store, symbols, ciks, counts, errors)
    if not symbols:
        log.error("Empty universe; nothing to screen")
        return 2

    # Data is strictly before as_of; screening "as of tomorrow" includes today's close.
    as_of = args.as_of or date.today() + timedelta(days=1)
    rows = run_screen(store, symbols, as_of, benchmark(), top_n=args.top_n, sectors=sectors)
    store.upsert_screens(rows)
    picks = [r["ticker"] for r in sorted((r for r in rows if r["selected"]), key=lambda r: r["rank"])]
    counts["screened"] = len(rows)
    counts["quality_pass"] = sum(r["quality_pass"] for r in rows)
    log.info("Top %d: %s", len(picks), ", ".join(picks))

    if picks and not args.no_backfill:
        backfill_picks(store, picks, counts, errors)

    status = "ok" if not errors else ("error" if not picks else "partial")
    store.log_run({
        "job": "screen", "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(), "status": status,
        "counts": dict(counts), "errors": errors[:200],
    })
    log.info("Screen done: status=%s counts=%s errors=%d", status, dict(counts), len(errors))
    # A few constituents without data is normal (new listings, odd tickers): only fail if no picks.
    return 0 if picks else 1


if __name__ == "__main__":
    sys.exit(main())
