"""M10 evaluation: score every past view and baseline once its horizon has closed, then report.

    python -m evaluation.run                 # refresh prices, score, write reports/evaluation.md + .json
    python -m evaluation.run --no-refresh    # score with the prices already stored

Also runs at the end of every weekly screen. Scoring is incremental: a (view, horizon) pair is
written once, when its window has closed, and never recomputed.

What is scored (the protocol in docs/paper, section 8):
  views      full system and the no_retrieval baseline, at 21, 63 and 252 trading days
  baselines  per screen: screen_picks (the top N, treated as bullish), random_quality (a seeded
             random sample of the same size from quality-passing stocks), quality_universe (all of them)
The primary analysis is the 63-trading-day horizon of the 1-3 month views, once 12 weeks have closed.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from common import logging_setup, progress
from common.config import ROOT, benchmark
from evaluation import metrics
from evaluation.outcomes import HORIZON_OF_VIEW, HORIZONS, forward_excess, hit

log = logging.getLogger("evaluation")

REPORT_DIR = ROOT / "reports"
PRIMARY_HORIZON = 63
REQUIRED_WEEKS = 12
BASELINES = ("screen_picks", "random_quality", "quality_universe")


class Prices:
    """Adjusted-close series loaded once per ticker."""

    def __init__(self, store, start: date):
        self.store, self.start, self._cache = store, start, {}

    def series(self, ticker: str) -> list[tuple[str, float]]:
        if ticker not in self._cache:
            self._cache[ticker] = self.store.price_closes(ticker, self.start)
        return self._cache[ticker]

    def as_dict(self, ticker: str) -> dict[str, float]:
        return dict(self.series(ticker))


# ------------------------------------------------------------------ scoring
def score_views(store, prices: Prices, bench: dict[str, float]) -> Counter:
    done, rows, c = store.performance_keys(), [], Counter()
    for v in store.eval_views():
        for h in HORIZONS:
            if (v["id"], h) in done:
                c["already"] += 1
                continue
            out = forward_excess(prices.series(v["ticker"]), bench, v["as_of"], h)
            if out is None:
                c["pending"] += 1
                continue
            rows.append({"suggestion_id": v["id"], "horizon_days": h, **out, "hit": hit(v["stance"], out["excess_return"])})
            c["scored"] += 1
    if rows:
        store.upsert_performance(rows)
    return c


def baseline_sets(screen_rows: list[dict]) -> dict[tuple[str, str], list[str]]:
    """{(as_of, baseline): tickers} for every screen. The random sample is seeded by the date,
    so re-running the evaluation always picks the same stocks."""
    by_date: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"quality": [], "picks": []})
    for r in screen_rows:
        d = str(r["as_of"])[:10]
        by_date[d]["quality"].append(r["ticker"])
        if r["selected"]:
            by_date[d]["picks"].append(r["ticker"])
    out = {}
    for d, s in by_date.items():
        quality, picks = sorted(s["quality"]), sorted(s["picks"])
        if not picks:
            continue
        out[(d, "screen_picks")] = picks
        out[(d, "random_quality")] = sorted(random.Random(f"ti-agent-{d}").sample(quality, min(len(picks), len(quality))))
        out[(d, "quality_universe")] = quality
    return out


def score_baselines(store, prices: Prices, bench: dict[str, float]) -> Counter:
    done, rows, c = store.baseline_keys(), [], Counter()
    for (d, name), tickers in baseline_sets(store.screen_sets()).items():
        for t in tickers:
            for h in HORIZONS:
                if (d, name, t, h) in done:
                    continue
                out = forward_excess(prices.series(t), bench, d, h)
                if out is None:
                    c["pending"] += 1
                    continue
                rows.append({"as_of": d, "baseline": name, "ticker": t, "horizon_days": h, **out})
                c["scored"] += 1
    if rows:
        store.upsert_baselines(rows)
    return c


# ------------------------------------------------------------------ summary
def summarize(store, faithfulness: dict | None = None) -> dict:
    scored = store.eval_scored()
    views = store.eval_views()
    base = store.eval_baselines()
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "views": {}, "baselines": {}, "comparisons": {}, "faithfulness": faithfulness}

    weeks_written = sorted({metrics.week_of(v["as_of"]) for v in views if v["variant"] == "full"})
    primary = [r for r in scored if r["variant"] == "full" and r["horizon"] == "medium"
               and r["horizon_days"] == PRIMARY_HORIZON]
    primary_weeks = sorted({metrics.week_of(r["as_of"]) for r in primary})
    out["status"] = {
        "weeks_with_views": len(weeks_written),
        "views_written": sum(v["variant"] == "full" for v in views),
        "primary_weeks_closed": len(primary_weeks),
        "primary_weeks_required": REQUIRED_WEEKS,
        "primary_ready": len(primary_weeks) >= REQUIRED_WEEKS,
    }

    for variant in sorted({r["variant"] for r in views}):
        for h in HORIZONS:
            rows = [r for r in scored if r["variant"] == variant and r["horizon_days"] == h]
            # Each view is judged at the horizon it is about; other horizons are reported too.
            own = [r for r in rows if HORIZON_OF_VIEW.get(r["horizon"]) == h] or rows
            out["views"][f"{variant}/{h}"] = {
                "scored": len(rows),
                "hit_rate": metrics.hit_rate(r["hit"] for r in own),
                "bullish_excess": metrics.bootstrap_ci(metrics.group_by_week([r for r in rows if r["stance"] == "bullish"])),
                "bearish_excess": metrics.bootstrap_ci(metrics.group_by_week([r for r in rows if r["stance"] == "bearish"])),
                "long_short": metrics.bootstrap_ci(metrics.long_short_by_week(rows)),
                "calibration": metrics.calibration([(r["confidence"], r["hit"]) for r in own if r["hit"] is not None]),
            }

    for name in BASELINES:
        for h in HORIZONS:
            rows = [r for r in base if r["baseline"] == name and r["horizon_days"] == h]
            out["baselines"][f"{name}/{h}"] = {
                "scored": len(rows),
                "excess": metrics.bootstrap_ci(metrics.group_by_week(rows)),
                "beat_benchmark": metrics.hit_rate(r["excess_return"] > 0 for r in rows),
            }

    # Does the agent add anything over the screen it starts from? Bullish views vs the screen's picks.
    for h in HORIZONS:
        system = metrics.group_by_week([r for r in scored if r["variant"] == "full" and r["horizon_days"] == h
                                        and r["stance"] == "bullish"])
        picks = metrics.group_by_week([r for r in base if r["baseline"] == "screen_picks" and r["horizon_days"] == h])
        out["comparisons"][f"bullish_vs_screen_picks/{h}"] = metrics.bootstrap_ci(
            metrics.paired_difference_by_week(system, picks))
        if any(r["variant"] == "no_retrieval" for r in scored):
            full = metrics.long_short_by_week([r for r in scored if r["variant"] == "full" and r["horizon_days"] == h])
            nor = metrics.long_short_by_week([r for r in scored if r["variant"] == "no_retrieval" and r["horizon_days"] == h])
            out["comparisons"][f"long_short_full_vs_no_retrieval/{h}"] = metrics.bootstrap_ci(
                metrics.paired_difference_by_week(full, nor))
    return out


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.2f}%"


def _ci(d: dict) -> str:
    if d.get("mean") is None:
        return "—"
    s = _pct(d["mean"])
    return s + (f" [{_pct(d['lo'])}, {_pct(d['hi'])}]" if d.get("lo") is not None else " (one week, no CI)")


def render_markdown(s: dict) -> str:
    st = s["status"]
    lines = [
        "# TI Agent evaluation", "",
        f"Generated {s['generated_at']}. Excess returns are over the benchmark; intervals are 95% week-block "
        f"bootstrap intervals. Protocol: docs/paper, section 8.", "",
        "## Status", "",
        f"- Weeks with views: **{st['weeks_with_views']}** ({st['views_written']} views of the full system)",
        f"- Weeks whose 1–3 month views have closed at {PRIMARY_HORIZON} trading days: "
        f"**{st['primary_weeks_closed']} of {st['primary_weeks_required']}** needed for the primary analysis",
        f"- Primary analysis: **{'ready' if st['primary_ready'] else 'not yet: results below are preliminary'}**",
        "",
        "## Views", "",
        "| Variant / horizon | Scored | Hit rate (own horizon) | p (> 50%) | Bullish excess | Bearish excess | "
        "Long − short | Brier | ECE |",
        "|---|---:|---:|---:|---|---|---|---:|---:|",
    ]
    def num(x, fmt=".3f"):
        return "—" if x is None else format(x, fmt)

    for k, v in s["views"].items():
        hr, cal = v["hit_rate"], v["calibration"]
        rate = f"{hr['hits']}/{hr['n']} ({hr['rate']:.0%})" if hr["n"] else "—"
        lines.append(f"| {k} | {v['scored']} | {rate} | {num(hr['p_value'])} | {_ci(v['bullish_excess'])} "
                     f"| {_ci(v['bearish_excess'])} | {_ci(v['long_short'])} | {num(cal['brier'])} "
                     f"| {num(cal['ece'])} |")
    lines += ["", "## Baselines", "",
              "| Baseline / horizon | Stocks scored | Mean excess | Beat the benchmark |",
              "|---|---:|---|---:|"]
    for k, v in s["baselines"].items():
        b = v["beat_benchmark"]
        lines.append(f"| {k} | {v['scored']} | {_ci(v['excess'])} | "
                     + (f"{b['hits']}/{b['n']} ({b['rate']:.0%})" if b["n"] else "—") + " |")
    lines += ["", "## Comparisons (paired by week)", ""]
    for k, v in s["comparisons"].items():
        lines.append(f"- {k}: {_ci(v)} over {v['weeks']} week(s)")
    f = s.get("faithfulness")
    lines += ["", "## Citation faithfulness", ""]
    if f:
        lines.append(f"- Items: {f['items']}; support rate A {f['support_rate_a']}, B {f['support_rate_b']}; "
                     f"Cohen's kappa {f['kappa']}")
    else:
        lines.append("- No annotations yet (`python -m evaluation.faithfulness sample`).")
    return "\n".join(lines) + "\n"


def _latest_faithfulness() -> dict | None:
    p = REPORT_DIR / "faithfulness.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except Exception:
        return None


def evaluate(store, refresh: bool = True, today: date | None = None) -> dict:
    """Score what has closed and write the report. Returns the summary."""
    today = today or date.today()
    views = store.eval_views()
    screens = store.screen_sets()
    starts = [date.fromisoformat(str(v["as_of"])[:10]) for v in views] + \
             [date.fromisoformat(str(r["as_of"])[:10]) for r in screens]
    start = (min(starts) if starts else today) - timedelta(days=10)
    bench_symbol = benchmark()

    if refresh:
        # Picks that dropped out of the screen no longer get daily prices; bring them up to date.
        tickers = sorted({v["ticker"] for v in views} | {r["ticker"] for r in screens} | {bench_symbol})
        stored = store.price_marks(tickers) if hasattr(store, "price_marks") else {}
        stale = [t for t in tickers if t not in stored
                 or date.fromisoformat(str(stored[t]["last"])[:10]) < today - timedelta(days=4)]
        if stale:
            from orchestration.screen_run import PRICE_HISTORY_DAYS, _refresh_prices

            with progress.step("Refresh prices", total=len(stale)) as st:
                _refresh_prices(store, stale, today - timedelta(days=PRICE_HISTORY_DAYS), today, Counter(), [], st)
        else:
            progress.skip("Refresh prices", "all up to date")

    prices = Prices(store, start)
    bench = prices.as_dict(bench_symbol)
    with progress.step("Score views") as st:
        c = score_views(store, prices, bench)
        st.set_result(f"{c['scored']} new, {c['pending']} still open")
    with progress.step("Score baselines") as st:
        c = score_baselines(store, prices, bench)
        st.set_result(f"{c['scored']} new, {c['pending']} still open")
    with progress.step("Write report") as st:
        summary = summarize(store, _latest_faithfulness())
        REPORT_DIR.mkdir(exist_ok=True)
        (REPORT_DIR / "evaluation.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
        (REPORT_DIR / "evaluation.md").write_text(render_markdown(summary), encoding="utf-8")
        s = summary["status"]
        st.set_result(f"reports/evaluation.md · primary {s['primary_weeks_closed']}/{s['primary_weeks_required']} weeks")
    return summary


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description="Score past views and baselines against realised returns")
    p.add_argument("--no-refresh", action="store_true", help="Use the prices already stored")
    args = p.parse_args(argv)
    from common.store import Store

    with progress.workflow("Evaluation", ["Refresh prices", "Score views", "Score baselines", "Write report"]):
        evaluate(Store(), refresh=not args.no_refresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
