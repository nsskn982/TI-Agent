"""Weekly screen of the S&P 500 + S&P MidCap 400 (Windows scheduled task, Friday night, before the
weekly agent run).

    python -m orchestration.screen_run                    # refresh universe + data, screen, backfill picks
    python -m orchestration.screen_run --skip-refresh     # re-screen from data already in the database
    python -m orchestration.screen_run --top-n 20 --as-of 2026-11-14

Steps:
  1. S&P 500 + S&P 400 constituents (Wikipedia) -> tickers (in_sp500 / in_sp400, sector, CIK)
  2. prices for every constituent + the benchmark (batched yfinance download): ~800 days on the
     first run, only new days afterwards
  3. SEC XBRL fundamentals for every constituent
  4. screen: momentum among quality companies -> `screens`, top N marked `selected`
  5. picks with no documents yet get a news + filings backfill, then chunk/embed/sentiment
  6. retention: delete data no module reads any more (orchestration/retention.py)

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
from ingestion import edgar, fundamentals, prices, refresh, universe
from ingestion.run import FUNDAMENTALS_EXTRA_DAYS, PRICE_HISTORY_DAYS
from quant.screen import run_screen

log = logging.getLogger("screen")

BACKFILL_DAYS = 730


def refresh_universe(store, counts: Counter, errors: list) -> tuple[list[str], dict[str, dict], dict[str, int]]:
    """Upsert S&P 500 + S&P 400 constituents.
    Returns (symbols, {symbol: {"sector", "index"}}, {symbol: cik})."""
    try:
        members = universe.fetch_universe()
    except Exception as exc:
        errors.append({"source": "universe", "key": "wikipedia", "error": f"{type(exc).__name__}: {exc}"[:500]})
        log.error("Could not fetch the index lists (%s); using the stored universe", exc)
        return store.universe_symbols(), {}, {}
    current = {m["symbol"] for m in members}
    dropped = [s for s in store.universe_symbols() if s not in current]

    def row(m):
        r = {"symbol": m["symbol"], "name": m["name"], "sector": m["sector"],
             "in_sp500": m["index"] == "S&P 500", "in_sp400": m["index"] == "S&P 400"}
        return {**r, "cik": m["cik"]} if m["cik"] else r
    rows = [row(m) for m in members]
    # Bulk upserts need identical keys per batch: rows with and without a CIK go separately,
    # so a missing CIK (the S&P 400 table has none) never blanks a stored one.
    store.upsert_tickers([r for r in rows if "cik" in r])
    store.upsert_tickers([r for r in rows if "cik" not in r])
    if dropped:
        store.upsert_tickers([{"symbol": s, "in_sp500": False, "in_sp400": False} for s in dropped])
        log.info("Left the indexes since last run: %s", ", ".join(dropped))
    counts["universe"] = len(members)
    counts["sp500"] = sum(m["index"] == "S&P 500" for m in members)
    counts["sp400"] = sum(m["index"] == "S&P 400" for m in members)
    return ([m["symbol"] for m in members],
            {m["symbol"]: {"sector": m["sector"], "index": m["index"]} for m in members},
            {m["symbol"]: m["cik"] for m in members if m["cik"]})


def refresh_data(store, symbols: list[str], ciks: dict[str, int], counts: Counter, errors: list) -> None:
    today = date.today()
    bench = benchmark()
    store.upsert_tickers([{"symbol": bench}])
    full_since = today - timedelta(days=PRICE_HISTORY_DAYS)
    everyone = symbols + [bench]
    stored = refresh.marks(store, "price_marks", everyone)
    starts = {s: refresh.price_since(stored.get(s), full_since, today) for s in everyone}
    backfill = [s for s in everyone if starts[s] == full_since]
    update = [s for s in everyone if starts[s] != full_since]
    got = prices.fetch_many(backfill, full_since) if backfill else {}
    if update:
        recent = prices.fetch_many(update, min(starts[s] for s in update))
        rebased = [s for s in update if refresh.rebased(stored.get(s), recent.get(s) or [])]
        got.update(recent)
        if rebased:
            log.info("Re-fetching full history for %d re-based tickers (dividends/splits)", len(rebased))
            got.update(prices.fetch_many(rebased, full_since))
        counts["prices_full"], counts["prices_incremental"] = len(backfill) + len(rebased), len(update) - len(rebased)
    for s in everyone:
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
    filed = refresh.marks(store, "fundamentals_marks", symbols)
    for s in symbols:
        cik = (sec_map.get(s) or {}).get("cik") or ciks.get(s)
        if not cik:
            errors.append({"source": "fundamentals", "key": s, "error": "no CIK"})
            continue
        try:
            rows = fundamentals.fetch_fundamentals(session, s, cik, refresh.filed_since(filed.get(s), filed_since))
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
    p = argparse.ArgumentParser(description="Weekly screen: S&P 500 + S&P MidCap 400")
    p.add_argument("--as-of", type=date.fromisoformat, default=None, help="Screen date (default: tomorrow, "
                   "so the latest close counts)")
    p.add_argument("--top-n", type=int, default=env_int("SCREEN_TOP_N", 20))
    p.add_argument("--skip-refresh", action="store_true", help="Don't download; screen stored data")
    p.add_argument("--no-backfill", action="store_true")
    p.add_argument("--keep-old", action="store_true", help="Skip the retention step (keep old data)")
    args = p.parse_args(argv)

    from common.store import Store

    store = Store()
    started = datetime.now(timezone.utc)
    counts: Counter = Counter()
    errors: list[dict] = []

    if args.skip_refresh:
        symbols, info = store.universe_symbols(), {}
    else:
        symbols, info, ciks = refresh_universe(store, counts, errors)
        refresh_data(store, symbols, ciks, counts, errors)
    if not symbols:
        log.error("Empty universe; nothing to screen")
        return 2

    # Data is strictly before as_of; screening "as of tomorrow" includes today's close.
    as_of = args.as_of or date.today() + timedelta(days=1)
    rows = run_screen(store, symbols, as_of, benchmark(), top_n=args.top_n, info=info)
    store.upsert_screens(rows)
    picks = [r["ticker"] for r in sorted((r for r in rows if r["selected"]), key=lambda r: r["rank"])]
    counts["screened"] = len(rows)
    counts["quality_pass"] = sum(r["quality_pass"] for r in rows)
    log.info("Top %d: %s", len(picks), ", ".join(picks))

    if picks and not args.no_backfill:
        backfill_picks(store, picks, counts, errors)

    if not args.keep_old:
        from orchestration.retention import prune

        try:
            counts.update({f"pruned_{k}": v for k, v in prune(store).items() if v})
        except Exception as exc:
            errors.append({"source": "retention", "key": "prune", "error": f"{type(exc).__name__}: {exc}"[:300]})

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
