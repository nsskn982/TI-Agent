"""Retention: keep only the data some module still reads.

    python -m orchestration.retention              # prune now (also runs at the end of the weekly screen)
    python -m orchestration.retention --dry-run    # show the cut-off dates only

Each window is the longest look-back of the code that reads that table, plus slack:

| Table          | Kept                 | Longest reader                                       |
|----------------|----------------------|------------------------------------------------------|
| prices         | 800 days             | backfill window (screen 420 d, features 400 d)       |
| fundamentals   | filed in last ~4 yrs | backfill 730 d + 760 d for year-ago TTM figures      |
| macro_series   | 600 days             | quant.macro 500 d + release lags                     |
| news           | 400 days             | Finnhub serves ~1 year; sentiment uses 91 days       |
| filings        | 800 days             | 730-day backfill                                     |
| screens        | 400 days             | website/app history                                  |
| tool_calls, ingestion_runs | 180 days | ops/audit logs                                      |

Documents and chunks are also dropped for tickers that are neither on the watchlist nor
selected by a screen in the last 8 weeks (they are backfilled again if they come back), and
filing/news bodies are cleared once chunked and scored. Chunks cited by any suggestion are
never deleted, so every citation on the website keeps working.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from common import logging_setup
from common.config import benchmark
from ingestion.run import FUNDAMENTALS_EXTRA_DAYS, PRICE_HISTORY_DAYS

log = logging.getLogger("retention")

BACKFILL_DAYS = 730
KEEP_DAYS = {
    "prices": PRICE_HISTORY_DAYS,
    "fundamentals": BACKFILL_DAYS + FUNDAMENTALS_EXTRA_DAYS,
    "macro": 600,
    "news": 400,
    "filings": 800,
    "screens": 400,
    "logs": 180,
}
FOCUS_WEEKS = 8


def cutoffs(today: date | None = None) -> tuple[dict[str, date], date]:
    today = today or date.today()
    return ({k: today - timedelta(days=v) for k, v in KEEP_DAYS.items()},
            today - timedelta(weeks=FOCUS_WEEKS))


def prune(store, today: date | None = None) -> dict[str, int]:
    keep, focus_since = cutoffs(today)
    counts = store.prune(keep, focus_since, benchmark())
    log.info("Retention: %s", {k: v for k, v in counts.items() if v} or "nothing to delete")
    return counts


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description="Delete data no module reads any more")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.dry_run:
        keep, focus_since = cutoffs()
        for k, v in keep.items():
            print(f"{k:<14} before {v}")
        print(f"{'focus':<14} picks since {focus_since}")
        return 0
    from common.store import Store

    prune(Store())
    return 0


if __name__ == "__main__":
    sys.exit(main())
