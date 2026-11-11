"""Pages: dashboard, ticker detail, citation viewer, pipeline status."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from common.config import benchmark
from dashboard import repo as repo_mod

log = logging.getLogger("dashboard")


def _attach_citations(repo, suggestions: list[dict]) -> None:
    """Replace each suggestion's chunk ids with the cited passages (one query per page)."""
    ids = [i for s in suggestions for i in repo_mod.chunk_ids(s.get("sources"))]
    found = repo.chunks(ids)
    for s in suggestions:
        s["citations"] = [{"ref": f"chunk_{i}", "id": i, **found[i]} if i in found
                          else {"ref": f"chunk_{i}", "id": i, "missing": True}
                          for i in repo_mod.chunk_ids(s.get("sources"))]


def _mark_changes(repo, run: dict, rows: list[dict]) -> None:
    """Tag each suggestion against the previous good run: new, changed (from what) or unchanged."""
    prev = next((r for r in repo.agent_runs() if r["id"] < run["id"] and r["status"] in ("ok", "partial")), None)
    before = {(p["ticker"], p["horizon"]): p["stance"] for p in repo.suggestions_for_run(prev["id"])} if prev else {}
    for s in rows:
        old = before.get((s["ticker"], s["horizon"]))
        s["change"] = "new" if old is None else ("unchanged" if old == s["stance"] else "changed")
        s["previous_stance"] = old


@login_required
def home(request):
    repo = repo_mod.get_repo()
    run = repo.latest_good_run()
    rows = repo.suggestions_for_run(run["id"]) if run else []
    _attach_citations(repo, rows)
    if run:
        _mark_changes(repo, run, rows)
    by_ticker: dict[str, dict] = defaultdict(dict)
    for s in rows:
        by_ticker[s["ticker"]][s["horizon"]] = s
    cards = [{"ticker": t, "medium": h.get("medium"), "long": h.get("long")} for t, h in sorted(by_ticker.items())]
    stances = [s["stance"] for s in rows]
    stats = {
        "tickers": len(cards), "views": len(rows),
        "bullish": stances.count("bullish"), "neutral": stances.count("neutral"), "bearish": stances.count("bearish"),
        "sources": len({c["id"] for s in rows for c in s["citations"] if not c.get("missing")}),
        "changed": sum(s.get("change") in ("new", "changed") for s in rows),
    }
    return render(request, "dashboard/home.html", {"run": run, "cards": cards, "stats": stats, "nav": "home"})


@login_required
def ticker_detail(request, ticker: str):
    repo = repo_mod.get_repo()
    ticker = ticker.upper()
    if ticker not in {t["symbol"] for t in repo.tickers()}:
        raise Http404(f"{ticker} is not on the watchlist")
    bench = benchmark()

    def rebased(rows):
        pts = [(r["date"], r.get("adj_close") or r.get("close")) for r in rows if (r.get("adj_close") or r.get("close"))]
        if not pts:
            return []
        base = pts[0][1]
        return [{"date": d, "value": round(v / base * 100, 2), "price": round(v, 2)} for d, v in pts]

    series = {"ticker": rebased(repo.price_history(ticker)), "bench": rebased(repo.price_history(bench))}
    try:
        feats = repo.features(ticker)
    except Exception:  # a features hiccup shouldn't take the page down
        log.exception("features failed for %s", ticker)
        feats = {}
    history = repo.ticker_suggestions(ticker)
    _attach_citations(repo, history)
    return render(request, "dashboard/ticker.html", {
        "ticker": ticker, "bench": bench, "series": series, "features": feats,
        "latest": {h: next((s for s in history if s["horizon"] == h), None) for h in ("medium", "long")},
        "history": history, "nav": "ticker",
    })


@login_required
def citation(request, chunk_id: int):
    repo = repo_mod.get_repo()
    chunk = repo.chunks([chunk_id]).get(chunk_id)
    if chunk is None:
        raise Http404("No such passage")
    return render(request, "dashboard/citation.html", {"chunk": chunk, "ref": f"chunk_{chunk_id}"})


def _consecutive_ok_days(runs: list[dict]) -> int:
    """Phase 1 gate: consecutive most-recent days where every ingestion+processing run was ok."""
    by_day: dict[str, set] = defaultdict(set)
    for r in runs:
        by_day[str(r["started_at"])[:10]].add(r["status"])
    streak = 0
    for day in sorted(by_day, reverse=True):
        if by_day[day] == {"ok"}:
            streak += 1
        else:
            break
    return streak


@login_required
def status(request):
    repo = repo_mod.get_repo()
    ingestion = repo.ingestion_runs()
    agent = repo.agent_runs()
    ok_weeks = sorted({r["as_of"] for r in agent if r["status"] == "ok"}, reverse=True)
    for r in ingestion:
        r["n_errors"] = len(r.get("errors") or [])
    return render(request, "dashboard/status.html", {
        "ingestion": ingestion, "agent": agent, "nav": "status",
        "p1_streak": _consecutive_ok_days(ingestion), "p1_target": 7,
        "p3_weeks": len(ok_weeks), "p3_target": 4,
        "today": date.today(), "now": datetime.now(),
    })
