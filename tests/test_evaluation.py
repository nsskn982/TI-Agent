"""M10 evaluation: outcomes, metrics, scoring against stored views and baselines, faithfulness files,
and the no-retrieval agent baseline."""
import csv
import json
from datetime import date, timedelta

import pandas as pd
import pytest

from agent.tools import ToolContext, tool_specs
from evaluation import faithfulness, metrics
from evaluation import run as ev
from evaluation.outcomes import forward_excess, hit
from tests.fakes import FakeStore
from tests.test_agent import AS_OF, WRITE_UP


def series(start, n, f):
    days = [d.date().isoformat() for d in pd.bdate_range(start, periods=n)]
    return [(d, f(i)) for i, d in enumerate(days)]


# ------------------------------------------------------------------ outcomes
def test_forward_excess_entry_exit_and_pending():
    stock = series("2026-01-01", 40, lambda i: 100 * (1.01 ** i))
    bench = dict(series("2026-01-01", 40, lambda i: 100.0))
    out = forward_excess(stock, bench, "2026-01-03", 21)  # a Saturday: entry is the next trading day
    assert out["entry_date"] == "2026-01-05"
    assert out["exit_date"] == stock[[d for d, _ in stock].index("2026-01-05") + 21][0]
    assert out["excess_return"] == pytest.approx(1.01 ** 21 - 1)
    assert forward_excess(stock, bench, "2026-01-03", 63) is None   # window not closed yet


def test_hit_by_stance():
    assert hit("bullish", 0.02) and not hit("bullish", -0.01)
    assert hit("bearish", -0.02) and not hit("bearish", 0.01)
    assert hit("neutral", 0.5) is None


# ------------------------------------------------------------------ metrics
def test_hit_rate_and_binomial_test():
    r = metrics.hit_rate([True] * 15 + [False] * 5 + [None] * 3)
    assert r["n"] == 20 and r["hits"] == 15 and r["rate"] == 0.75
    assert 0.01 < r["p_value"] < 0.03                 # P(X >= 15 | n=20, p=0.5) is about 0.021
    assert metrics.hit_rate([None])["rate"] is None


def test_bootstrap_resamples_weeks():
    one = metrics.bootstrap_ci({"2026-W01": [0.01, 0.03]})
    assert one["mean"] == pytest.approx(0.02) and one["lo"] is None   # one week: no interval
    many = metrics.bootstrap_ci({f"2026-W{i:02d}": [0.01 * (i % 3)] for i in range(1, 13)}, seed=1)
    assert many["lo"] <= many["mean"] <= many["hi"] and many["weeks"] == 12


def test_long_short_and_paired_difference():
    rows = [{"stance": "bullish", "as_of": "2026-11-14", "excess_return": 0.04},
            {"stance": "bearish", "as_of": "2026-11-14", "excess_return": -0.02},
            {"stance": "bullish", "as_of": "2026-11-21", "excess_return": 0.01}]   # no bearish that week
    assert metrics.long_short_by_week(rows) == {"2026-W46": [pytest.approx(0.06)]}
    d = metrics.paired_difference_by_week({"W1": [0.03, 0.01]}, {"W1": [0.01], "W2": [0.5]})
    assert d == {"W1": [pytest.approx(0.01)]}


def test_calibration_and_kappa():
    cal = metrics.calibration([(0.6, True), (0.6, False), (0.9, True)])
    assert cal["brier"] == pytest.approx(((0.4 ** 2) + (0.6 ** 2) + (0.1 ** 2)) / 3)
    assert {b["range"] for b in cal["bins"]} == {"0.60-0.65", "0.70-1.00"}
    assert metrics.cohen_kappa(["a", "a", "b", "b"], ["a", "a", "b", "b"]) == 1.0
    assert metrics.cohen_kappa(["a", "b", "a", "b"], ["a", "a", "b", "b"]) == pytest.approx(0.0)


# ------------------------------------------------------------------ scoring against the store
class EvalStore:
    def __init__(self):
        days = pd.bdate_range("2026-01-01", periods=120)
        self.px = {
            "SPY": [(d.date().isoformat(), 100 + i * 0.1) for i, d in enumerate(days)],
            "UP": [(d.date().isoformat(), 100 + i * 0.5) for i, d in enumerate(days)],      # beats SPY
            "DOWN": [(d.date().isoformat(), 100 - i * 0.2) for i, d in enumerate(days)],    # lags SPY
            "FLAT": [(d.date().isoformat(), 100.0) for d in days],
        }
        self.views = [
            {"id": 1, "run_id": 1, "ticker": "UP", "horizon": "medium", "stance": "bullish", "confidence": 0.6,
             "as_of": "2026-01-05", "variant": "full"},
            {"id": 2, "run_id": 1, "ticker": "DOWN", "horizon": "medium", "stance": "bearish", "confidence": 0.58,
             "as_of": "2026-01-05", "variant": "full"},
            {"id": 3, "run_id": 2, "ticker": "UP", "horizon": "medium", "stance": "neutral", "confidence": 0.55,
             "as_of": "2026-01-05", "variant": "no_retrieval"},
        ]
        self.screens = [{"as_of": "2026-01-04", "ticker": t, "selected": t in ("UP", "DOWN")}
                        for t in ("UP", "DOWN", "FLAT")]
        self.perf, self.base = {}, {}

    def price_closes(self, t, start):
        return [x for x in self.px.get(t, []) if x[0] >= start.isoformat()]

    def eval_views(self):
        return self.views

    def performance_keys(self):
        return set(self.perf)

    def upsert_performance(self, rows):
        for r in rows:
            self.perf[(r["suggestion_id"], r["horizon_days"])] = r

    def screen_sets(self):
        return self.screens

    def baseline_keys(self):
        return set(self.base)

    def upsert_baselines(self, rows):
        for r in rows:
            self.base[(r["as_of"], r["baseline"], r["ticker"], r["horizon_days"])] = r

    def eval_scored(self):
        v = {x["id"]: x for x in self.views}
        return [{**v[k[0]], **r} for k, r in self.perf.items()]

    def eval_baselines(self):
        return list(self.base.values())


def test_evaluate_scores_closed_windows_and_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "REPORT_DIR", tmp_path)
    store = EvalStore()
    summary = ev.evaluate(store, refresh=False, today=date(2026, 6, 30))

    # 120 trading days of prices: 21 and 63 close, 252 stays open.
    assert {h for _, h in store.perf} == {21, 63}
    assert store.perf[(1, 63)]["hit"] is True and store.perf[(2, 63)]["hit"] is True
    assert store.perf[(3, 63)]["hit"] is None                       # neutral: no direction
    v = summary["views"]["full/63"]
    assert v["hit_rate"]["hits"] == 2 and v["long_short"]["mean"] > 0

    # Baselines: the picks, a seeded random sample of the same size, and all quality-passing stocks.
    names = {(k[1], k[2]) for k in store.base if k[3] == 63}
    assert {t for b, t in names if b == "screen_picks"} == {"UP", "DOWN"}
    assert len({t for b, t in names if b == "random_quality"}) == 2
    assert {t for b, t in names if b == "quality_universe"} == {"UP", "DOWN", "FLAT"}
    assert summary["status"]["primary_ready"] is False and summary["status"]["primary_weeks_closed"] == 1

    text = (tmp_path / "evaluation.md").read_text(encoding="utf-8")
    assert "not yet" in text and "full/63" in text and "screen_picks/63" in text
    assert json.loads((tmp_path / "evaluation.json").read_text())["status"]["views_written"] == 2

    # Incremental: a second run scores nothing new.
    before = dict(store.perf)
    ev.evaluate(store, refresh=False, today=date(2026, 6, 30))
    assert store.perf == before


def test_random_baseline_is_reproducible():
    rows = [{"as_of": "2026-01-04", "ticker": f"T{i:02d}", "selected": i < 3} for i in range(30)]
    a = ev.baseline_sets(rows)
    assert a == ev.baseline_sets(list(reversed(rows)))
    assert len(a[("2026-01-04", "random_quality")]) == 3


# ------------------------------------------------------------------ citation faithfulness
def test_faithfulness_sample_and_score(tmp_path, monkeypatch):
    monkeypatch.setattr(faithfulness, "OUT_DIR", tmp_path)
    monkeypatch.setattr(faithfulness, "REPORT", tmp_path / "faithfulness.json")

    class S:
        def faithfulness_pairs(self, variant):
            return [{"suggestion_id": i // 2, "ticker": "UP", "horizon": "medium" if i % 3 else "long",
                     "as_of": "2026-01-05", "thesis": "Thesis text.", "bull_case": "Bull.", "bear_case": "Bear.",
                     "valuation": "Val.", "chunk_id": i, "source": "news" if i % 2 else "filing",
                     "doc_type": "10-Q", "published_at": "2026-01-01", "content": f"passage {i}"} for i in range(40)]

    path = faithfulness.sample(S(), n=12, seed=3)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert 4 <= len(rows) <= 12 and {r["source"] for r in rows} == {"news", "filing"}
    for i, r in enumerate(rows):
        r["annotator_a"] = "supported" if i % 4 else "partial"
        r["annotator_b"] = "supported" if i % 4 else "unsupported"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=faithfulness.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    res = faithfulness.score(path)
    assert res["labelled_by_both"] == len(rows) and 0 < res["support_rate_a"] < 1
    assert res["kappa"] is not None and (tmp_path / "faithfulness.json").exists()


# ------------------------------------------------------------------ no-retrieval baseline
def test_no_retrieval_variant_has_no_search_and_no_citations():
    store = FakeStore()
    names = {t["function"]["name"] for t in tool_specs("no_retrieval")}
    assert "search_knowledge" not in names and "save_suggestion" in names
    ctx = ToolContext(store=store, retriever=None, ticker="AAPL", as_of=AS_OF, run_id=9, model="m",
                      variant="no_retrieval")
    assert ctx.execute("search_knowledge", {"query": "x"}).startswith("ERROR: unknown tool")
    base = dict(horizon="medium", stance="neutral", risks=["Valuation"], confidence=0.55,
                thesis="Momentum and margins look ordinary relative to the benchmark this quarter.", **WRITE_UP)
    assert "leave sources empty" in ctx.execute("save_suggestion", {**base, "sources": ["chunk_1"]})
    assert ctx.execute("save_suggestion", {**base, "sources": []}).startswith("Saved")
    row = store.suggestions[("AAPL", "medium", "2026-11-11", "no_retrieval")]
    assert row["variant"] == "no_retrieval" and row["sources"] == []


def test_full_variant_still_requires_a_citation():
    store = FakeStore()
    ctx = ToolContext(store=store, retriever=None, ticker="AAPL", as_of=AS_OF, run_id=1, model="m")
    out = ctx.execute("save_suggestion", dict(horizon="medium", stance="bullish", risks=["Valuation"],
                                              confidence=0.6, sources=[], **WRITE_UP,
                                              thesis="Demand came in above expectations and guidance was raised."))
    assert "at least one chunk id" in out
