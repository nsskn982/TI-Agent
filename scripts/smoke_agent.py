"""End-to-end agent smoke test with real data and a real model, no Supabase needed.

Loads real prices (yfinance), SEC filings + XBRL fundamentals (EDGAR), and, when the
keys are set, Finnhub news and FRED macro into the in-memory test store; embeds the
text with the real MiniLM model; then runs the Phase 3 agent against local Ollama.

    python scripts/smoke_agent.py --ticker AAPL
    python scripts/smoke_agent.py --ticker MSFT --no-think

Needs SEC_USER_AGENT (falls back to a generic dev contact for this one-off test).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.agent import run_ticker  # noqa: E402
from agent.llm import OllamaClient  # noqa: E402
from agent.tools import ToolContext  # noqa: E402
from common import logging_setup  # noqa: E402
from common.config import benchmark, env  # noqa: E402
from common.http import make_session  # noqa: E402
from ingestion import edgar, finnhub, fred, fundamentals, prices  # noqa: E402
from processing.embed import Embedder  # noqa: E402
from processing.run import process, score_sentiment  # noqa: E402
from retrieval.search import Retriever  # noqa: E402
from tests.fakes import FakeStore  # noqa: E402

log = logging.getLogger("smoke")


def load(store: FakeStore, ticker: str, as_of: date, filing_days: int) -> None:
    sec = make_session(env("SEC_USER_AGENT") or "TI-Agent dev-test contact@example.com")
    cik = edgar.load_cik_map(sec)[ticker]["cik"]
    bench = benchmark()
    store.upsert_tickers([{"symbol": ticker, "active": True}, {"symbol": bench, "active": False}])

    for t in (ticker, bench):
        store.upsert_prices(prices.fetch_prices(t, as_of - timedelta(days=800)))
    store.upsert_fundamentals(fundamentals.fetch_fundamentals(sec, ticker, cik, as_of - timedelta(days=1100)))
    filings = edgar.fetch_filings(sec, ticker, cik, as_of - timedelta(days=filing_days), max_chars=120_000)
    store.insert_documents(filings)
    log.info("Loaded %d price rows, %d XBRL facts, %d filings", len(store.prices), len(store.fundamentals),
             len(filings))

    if env("FINNHUB_API_KEY"):
        items = finnhub.fetch_company_news(make_session(), ticker, as_of - timedelta(days=90), as_of,
                                           env("FINNHUB_API_KEY"))
        store.insert_documents(finnhub.to_documents(ticker, items))
        log.info("Loaded %d news items", len(items))
    else:
        log.info("FINNHUB_API_KEY not set: no news (sentiment features will be empty)")
    if env("FRED_API_KEY"):
        s = make_session()
        for sid in fred.DEFAULT_SERIES:
            store.upsert_macro(fred.fetch_series(s, sid, as_of - timedelta(days=500), env("FRED_API_KEY")))
    else:
        log.info("FRED_API_KEY not set: get_macro will return no series")

    t0 = time.perf_counter()
    stats = process(store, Embedder())
    log.info("Embedded %d docs into %d chunks in %.0fs", stats["documents"], stats["chunks"],
             time.perf_counter() - t0)
    if any(d["source"] == "news" for d in store.documents.values()):
        from processing.sentiment import SentimentScorer

        score_sentiment(store, SentimentScorer())


def main() -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticker", default="AAPL")
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    p.add_argument("--filing-days", type=int, default=200, help="Look back this far for 10-K/10-Q/8-K")
    p.add_argument("--no-think", action="store_true")
    p.add_argument("--max-steps", type=int, default=12)
    args = p.parse_args()
    ticker = args.ticker.upper()

    llm = OllamaClient(think=not args.no_think)
    llm.check()
    store = FakeStore()
    load(store, ticker, args.as_of, args.filing_days)

    timings = []

    def on_call(row):
        timings.append(row)
        print(f"  [step {row['step']:>2}] {row['tool']}({json.dumps(row['arguments'])[:110]}) "
              f"-> {row['result_summary'][:150]!r}")

    original_chat = llm.chat

    def timed_chat(messages, tools):
        t0 = time.perf_counter()
        out = original_chat(messages, tools)
        print(f"  ... model turn {time.perf_counter() - t0:.1f}s, thinking {len(llm.last_thinking)} chars, "
              f"{len(out['tool_calls'])} tool call(s)")
        return out

    llm.chat = timed_chat
    ctx = ToolContext(store=store, retriever=Retriever(store, Embedder()), ticker=ticker, as_of=args.as_of,
                      run_id=0, model=llm.model, allowed_tickers={ticker}, on_call=on_call)
    print(f"\nRunning {llm.model} (think={llm.think}, num_ctx={llm.num_ctx}) on {ticker} as of {args.as_of}\n")
    t0 = time.perf_counter()
    res = run_ticker(llm, ctx, max_steps=args.max_steps)
    elapsed = time.perf_counter() - t0

    rejected = sum(1 for r in timings if r["tool"] == "save_suggestion" and r["result_summary"].startswith("ERROR"))
    print(f"\nComplete: {res.complete} | steps {res.steps} | tool calls {res.tool_calls} | "
          f"rejected saves {rejected} | {elapsed:.0f}s | error: {res.error}")
    for h, row in res.saved.items():
        print(f"\n--- {h} ---")
        print(json.dumps({k: row[k] for k in ("stance", "confidence", "thesis", "risks", "sources")}, indent=2))
    return 0 if res.complete else 1


if __name__ == "__main__":
    sys.exit(main())
