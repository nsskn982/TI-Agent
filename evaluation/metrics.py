"""Statistics for the evaluation protocol. Pure functions over plain rows, so they are easy to test.

Weeks are the unit of resampling: views written in the same week share market conditions, so the
bootstrap resamples whole weeks (a block bootstrap), not individual views.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable, Sequence

import numpy as np

RELIABILITY_BINS = (0.0, 0.5, 0.55, 0.6, 0.65, 0.7, 1.0)


def week_of(d: date | str) -> str:
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def hit_rate(hits: Iterable[bool | None]) -> dict:
    """Share of directional views that were right, with a one-sided binomial test against 50%."""
    xs = [h for h in hits if h is not None]
    n, k = len(xs), sum(bool(h) for h in xs)
    if n == 0:
        return {"n": 0, "hits": 0, "rate": None, "p_value": None}
    from scipy.stats import binomtest

    return {"n": n, "hits": k, "rate": k / n, "p_value": float(binomtest(k, n, 0.5, alternative="greater").pvalue)}


def bootstrap_ci(by_week: dict[str, Sequence[float]], n_boot: int = 2000, seed: int = 0,
                 level: float = 0.95) -> dict:
    """Mean of all values, with a confidence interval from resampling whole weeks."""
    weeks = [np.asarray(v, dtype=float) for v in by_week.values() if len(v)]
    if not weeks:
        return {"mean": None, "lo": None, "hi": None, "weeks": 0, "n": 0}
    allv = np.concatenate(weeks)
    out = {"mean": float(allv.mean()), "weeks": len(weeks), "n": int(allv.size), "lo": None, "hi": None}
    if len(weeks) < 2:
        return out  # one week can't be resampled meaningfully
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(weeks), len(weeks))
        means[i] = np.concatenate([weeks[j] for j in pick]).mean()
    a = (1 - level) / 2
    out["lo"], out["hi"] = float(np.quantile(means, a)), float(np.quantile(means, 1 - a))
    return out


def long_short_by_week(rows: Iterable[dict]) -> dict[str, list[float]]:
    """Per week: mean excess of bullish views minus mean excess of bearish views (weeks with both)."""
    bull: dict[str, list[float]] = defaultdict(list)
    bear: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("excess_return") is None:
            continue
        if r["stance"] == "bullish":
            bull[week_of(r["as_of"])].append(float(r["excess_return"]))
        elif r["stance"] == "bearish":
            bear[week_of(r["as_of"])].append(float(r["excess_return"]))
    return {w: [float(np.mean(bull[w]) - np.mean(bear[w]))] for w in bull if w in bear}


def group_by_week(rows: Iterable[dict], key: str = "excess_return") -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get(key) is not None:
            out[week_of(r["as_of"])].append(float(r[key]))
    return dict(out)


def paired_difference_by_week(a: dict[str, list[float]], b: dict[str, list[float]]) -> dict[str, list[float]]:
    """Per week present in both: mean(a) - mean(b). For 'system vs baseline' comparisons."""
    return {w: [float(np.mean(a[w]) - np.mean(b[w]))] for w in a if w in b and a[w] and b[w]}


def calibration(pairs: Sequence[tuple[float, bool]]) -> dict:
    """Brier score, reliability bins and expected calibration error for (confidence, correct) pairs."""
    pairs = [(float(p), bool(y)) for p, y in pairs if p is not None and y is not None]
    if not pairs:
        return {"n": 0, "brier": None, "ece": None, "bins": []}
    p = np.array([x for x, _ in pairs])
    y = np.array([float(v) for _, v in pairs])
    bins, ece = [], 0.0
    edges = RELIABILITY_BINS
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & ((p < hi) if i < len(edges) - 2 else (p <= hi))
        if m.any():
            mean_p, obs = float(p[m].mean()), float(y[m].mean())
            bins.append({"range": f"{lo:.2f}-{hi:.2f}", "n": int(m.sum()), "mean_confidence": mean_p, "observed": obs})
            ece += m.sum() / len(p) * abs(obs - mean_p)
    return {"n": len(pairs), "brier": float(np.mean((p - y) ** 2)), "ece": float(ece), "bins": bins}


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Agreement between two annotators beyond chance."""
    pairs = [(x, y) for x, y in zip(a, b) if x and y]
    if not pairs:
        return None
    labels = sorted({x for x, _ in pairs} | {y for _, y in pairs})
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    pe = sum((sum(x == l for x, _ in pairs) / n) * (sum(y == l for _, y in pairs) / n) for l in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)
