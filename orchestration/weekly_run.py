"""M8 weekly run: agent over this week's picks -> local database -> Telegram.

    python -m orchestration.weekly_run
    python -m orchestration.weekly_run --tickers AAPL --no-telegram

Exit code 0 = every ticker got both suggestions; 1 = partial; 2 = nothing produced.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from common import logging_setup, progress
from ingestion.run import load_watchlist

log = logging.getLogger("weekly_run")


def run(tickers: list[str], as_of: date, store, retriever, llm, notify=None,
        max_steps: int = 12, retries: int = 1) -> tuple[str, list, dict[str, str]]:
    from agent.agent import AgentResult, run_ticker
    from agent.llm import LLMError
    from agent.tools import ToolContext

    run_id = store.start_agent_run(as_of.isoformat(), llm.model)
    results: list[AgentResult] = []
    failures: dict[str, str] = {}
    try:
        for t in tickers:
            with progress.step(t) as st:
                res = _run_one(t, tickers, as_of, store, retriever, llm, run_id, max_steps, retries, st,
                               run_ticker, AgentResult, LLMError, ToolContext)
            results.append(res)
            if not res.complete:
                failures[t] = res.error or "incomplete"
            log.info("%s: saved %s in %d steps / %d tool calls", t, sorted(res.saved), res.steps, res.tool_calls)

        produced = sum(len(r.saved) for r in results)
        status = "ok" if not failures else ("partial" if produced else "error")
        store.finish_agent_run(run_id, status, "; ".join(f"{t}: {e}" for t, e in failures.items()) or None)
    except Exception as exc:
        store.finish_agent_run(run_id, "error", f"{type(exc).__name__}: {exc}"[:2000])
        if notify:
            notify(f"TI Agent weekly run crashed ({as_of}): {type(exc).__name__}: {exc}")
        raise

    if notify:
        from delivery.telegram import format_digest

        notify(format_digest(as_of.isoformat(), results, failures))
    return status, results, failures


def _run_one(t, tickers, as_of, store, retriever, llm, run_id, max_steps, retries, st,
             run_ticker, AgentResult, LLMError, ToolContext):
    """One ticker, with up to `retries` retries. Updates its progress step as tools are called."""
    rejected = 0

    def on_call(row: dict) -> None:
        nonlocal rejected
        if row.get("tool") == "save_suggestion" and str(row.get("result_summary", "")).startswith("ERROR"):
            rejected += 1
        st.set_note(f"step {row.get('step')} · {row.get('tool')}" + (f" · {rejected} rejected" if rejected else ""))
        store.log_tool_call(row)

    res = None
    for attempt in range(retries + 1):
        # A retry keeps horizons already saved, so it only has to produce what's missing.
        ctx = ToolContext(store=store, retriever=retriever, ticker=t, as_of=as_of, run_id=run_id,
                          model=llm.model, allowed_tickers=set(tickers), on_call=on_call,
                          saved=dict(res.saved) if res else {})
        try:
            res = run_ticker(llm, ctx, max_steps=max_steps)
        except LLMError as exc:
            res = AgentResult(ticker=t, saved=dict(ctx.saved), error=str(exc))
        if res.complete:
            break
        log.warning("%s attempt %d incomplete: %s", t, attempt + 1, res.error)
        if attempt < retries:
            st.set_note(f"retrying ({str(res.error)[:40]})")
    label = {"medium": "1-3m", "long": "6-24m"}
    views = " · ".join(f"{label.get(h, h)} {r.get('stance', '?')}" for h, r in sorted(res.saved.items(),
                                                                                         key=lambda x: x[0] != "medium"))
    st.set_result((views or "nothing saved") + (f" · retried" if attempt else ""))
    if not res.complete:
        st.problem()
    return res


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description="TI Agent weekly run (M8)")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                   help="Backtest date. The LLM's own training data may still leak hindsight.")
    p.add_argument("--max-steps", type=int, default=16)  # room for the longer write-up and one or two fixes
    p.add_argument("--no-telegram", action="store_true")
    args = p.parse_args(argv)

    from agent.llm import LLMError, OllamaClient
    from common.store import Store
    from delivery import telegram
    from processing.embed import Embedder
    from retrieval.search import Retriever

    notify = None if args.no_telegram else telegram.send
    store = Store()
    # Default: this week's S&P 500 screen picks, best first (watchlist.txt before the first screen).
    tickers = load_watchlist(args.tickers)
    if not args.tickers:
        from ingestion.universe import focus_tickers

        tickers = focus_tickers(store, tickers)

    llm = OllamaClient()
    with progress.workflow(f"Weekly AI run · {len(tickers)} picks", ["Load AI model", "Load search models", *tickers, "Export app data"]):
        try:
            with progress.step("Load AI model") as st:
                llm.check()
                # Load the model before this process loads MiniLM/torch, so it gets memory first.
                log.info("Loading %s into Ollama...", llm.model)
                llm.warmup()
                st.set_result(llm.model)
        except LLMError as exc:
            log.error("%s", exc)
            if notify:
                notify(f"TI Agent weekly run could not start: {exc}")
            return 2
        try:
            with progress.step("Load search models"):
                retriever = Retriever(store, Embedder())
            log.info("Analysing %d tickers: %s", len(tickers), ", ".join(tickers))
            status, _, failures = run(tickers, args.as_of, store, retriever, llm, notify, max_steps=args.max_steps)
        finally:
            llm.unload()  # ~6 GB back to Windows right away, not 30 minutes later
        try:  # this week's views for the app (site-data/data.json; push it to publish)
            from orchestration.export_app import export_if_configured

            export_if_configured(store)
        except Exception:
            log.exception("App data export failed")
    log.info("Weekly run finished: %s (%d failures)", status, len(failures))
    return {"ok": 0, "partial": 1}.get(status, 2)


if __name__ == "__main__":
    sys.exit(main())
