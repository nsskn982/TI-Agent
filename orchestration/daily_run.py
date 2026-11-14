"""Daily refresh in one view: ingest new data for the picks, then chunk, embed and score it.

    python -m orchestration.daily_run                    # what run_daily.cmd runs
    python -m orchestration.daily_run --days 730         # first-time backfill
    python -m orchestration.daily_run --tickers AAPL

Arguments are passed to `ingestion.run`. Ends by exporting the app's data (site-data/data.json).
Exit code 0 = everything ok, 1 = something failed.
"""
from __future__ import annotations

import sys

from common import logging_setup, progress

STEPS = ["Prices", "News", "Filings", "Fundamentals", "Macro", "Load models", "Chunk + embed", "News sentiment",
         "Export app data"]


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    from ingestion import run as ingest_run
    from processing import run as process_run

    with progress.workflow("Daily refresh", STEPS):
        rc_ingest = ingest_run.main(argv)
        if rc_ingest == 2:  # nothing to do (empty watchlist): don't process
            return 2
        rc_process = process_run.main([])  # embed whatever did arrive, even if one source failed
        rc_export = _export()
    return 0 if rc_ingest == 0 and rc_process == 0 and rc_export == 0 else 1


def _export() -> int:
    """New prices and news for the app (site-data/data.json); push it to publish."""
    import logging

    from common.store import Store
    from orchestration.export_app import export_if_configured

    try:
        export_if_configured(Store())
        return 0
    except Exception:
        logging.getLogger("daily_run").exception("App data export failed")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
