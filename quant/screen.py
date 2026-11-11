"""Weekly screen of the S&P 500 + S&P MidCap 400: momentum among quality companies.

Every constituent gets cheap, code-computed metrics; the top N by score are "selected" and
only those go through news/filings retrieval and the LLM agent.

Score (computed only among companies that pass the quality filter):

    0.50 * z(12-1 month return)        classic momentum: 12 months, skipping the latest month
  + 0.25 * z(6-month return vs SPY)
  + 0.25 * z(3-month return vs SPY)
  - 0.20 * z(6-month volatility)       very volatile names are penalised

z-scores are winsorised at +/-3 so one outlier can't dominate. Quality filter (point-in-time,
from SEC XBRL facts filed before the as-of date):
  * filings are recent (latest quarter ended < 200 days ago),
  * profitable: TTM net margin > 0,
  * free cash flow TTM > 0 where it can be computed. Skipped for the Financials sector, where
    operating cash flow mostly reflects lending/deposits; unknown FCF (no capex tag) doesn't fail.

References: Jegadeesh & Titman (1993) on 12-1 momentum; Asness, Frazzini & Pedersen,
"Quality Minus Junk" (2019) on profitability/cash-flow quality screens.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from quant import fundamentals as fund
from quant.features import clean, close_series

LOOKBACK_DAYS = 420          # >= 253 trading days
WEIGHTS = {"mom_12_1": 0.50, "rel_6m": 0.25, "rel_3m": 0.25}
VOL_PENALTY = 0.20
TOP_N = 20


def _ret(s: pd.Series, n: int, skip: int = 0) -> float | None:
    if len(s) <= n:
        return None
    end, start = s.iloc[-1 - skip], s.iloc[-1 - n]
    return float(end / start - 1) if start > 0 else None


def momentum_metrics(close: pd.Series, bench: pd.Series | None) -> dict | None:
    """Price-based metrics, or None if there isn't a full year of history."""
    close = close.dropna()
    if len(close) < 253:
        return None
    mom = _ret(close, 252, skip=21)            # 12-1 month
    r6, r3 = _ret(close, 126), _ret(close, 63)
    rel6 = rel3 = None
    if bench is not None and len(bench.dropna()) > 126:
        b = bench.dropna().reindex(close.index).ffill()
        b6, b3 = _ret(b, 126), _ret(b, 63)
        rel6 = (1 + r6) / (1 + b6) - 1 if r6 is not None and b6 is not None else None
        rel3 = (1 + r3) / (1 + b3) - 1 if r3 is not None and b3 is not None else None
    daily = np.log(close).diff().dropna().tail(126)
    vol = float(daily.std() * math.sqrt(252)) if len(daily) > 20 else None
    year = close.tail(252)
    return {
        "mom_12_1": mom,
        "ret_12m": _ret(close, 252),
        "ret_6m": r6,
        "ret_3m": r3,
        "ret_1m": _ret(close, 21),
        "rel_6m": rel6,
        "rel_3m": rel3,
        "vol_6m": vol,
        "last_close": float(close.iloc[-1]),
        # Levels traders watch day to day (facts about the price, not targets).
        "high_52w": float(year.max()),
        "low_52w": float(year.min()),
        "sma_50": float(close.tail(50).mean()),
        "sma_200": float(close.tail(200).mean()),
    }


def quality_check(f: dict, sector: str | None = None) -> tuple[bool, list[str]]:
    """(passes, notes). Notes explain a failure, or note unknown FCF on a pass.
    For banks/insurers ("Financials") operating cash flow mostly reflects lending and deposit
    flows, so free cash flow isn't a meaningful quality test there: only profitability counts."""
    if not f.get("period_end"):
        return False, ["no SEC financials"]
    if f.get("stale"):
        return False, ["financials out of date"]
    notes = []
    nm = f.get("net_margin")
    if nm is None or nm <= 0:
        return False, ["not profitable (TTM)"]
    if sector == "Financials":
        return True, ["financials: free cash flow not used"]
    fcf = f.get("fcf_ttm")
    if fcf is not None and fcf <= 0:
        return False, ["negative free cash flow (TTM)"]
    if fcf is None:
        notes.append("free cash flow not reported")
    return True, notes


def zscores(values: list[float]) -> list[float]:
    a = np.asarray(values, dtype=float)
    sd = a.std()
    if len(a) < 2 or sd == 0 or not np.isfinite(sd):
        return [0.0] * len(a)
    return list(np.clip((a - a.mean()) / sd, -3, 3))


def score_candidates(cands: list[dict], top_n: int = TOP_N) -> list[dict]:
    """Rank candidates in place. Each needs `quality_pass` and `metrics` (momentum keys)."""
    keys = list(WEIGHTS) + ["vol_6m"]
    eligible = [c for c in cands if c["quality_pass"] and all(c["metrics"].get(k) is not None for k in keys)]
    if eligible:
        z = {k: zscores([c["metrics"][k] for c in eligible]) for k in keys}
        for i, c in enumerate(eligible):
            c["score"] = sum(w * z[k][i] for k, w in WEIGHTS.items()) - VOL_PENALTY * z["vol_6m"][i]
    eligible.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(eligible, 1):
        c["rank"] = i
        c["selected"] = i <= top_n
    for c in cands:
        c.setdefault("rank", None)
        c.setdefault("score", None)
        c.setdefault("selected", False)
        if not c["quality_pass"]:
            continue
        if c["rank"] is None:
            c.setdefault("notes", []).append("not enough price history")
    return cands


PRICE_KEYS = ("mom_12_1", "ret_12m", "ret_6m", "ret_3m", "ret_1m", "rel_6m", "rel_3m", "vol_6m",
              "last_close", "high_52w", "low_52w", "sma_50", "sma_200")
FUND_KEYS = ("net_margin", "operating_margin", "fcf_ttm", "fcf_yield", "pe_ttm", "market_cap",
             "revenue_growth_yoy", "debt_to_equity")


def run_screen(store, tickers: list[str], as_of: date, bench_symbol: str, top_n: int = TOP_N,
               info: dict[str, dict] | None = None) -> list[dict]:
    """Screen `tickers` as of `as_of` (data strictly before it). Returns rows for `screens`.
    `info` maps ticker -> {"sector", "index"} (stored in metrics for the app)."""
    info = info or {}
    start = as_of - timedelta(days=LOOKBACK_DAYS)
    bench = close_series(store.get_prices(bench_symbol, start, as_of))
    cands = []
    for t in tickers:
        close = close_series(store.get_prices(t, start, as_of))
        mom = momentum_metrics(close, bench) or {}
        f = fund.fundamental_features(store.get_fundamentals(t, as_of), as_of, mom.get("last_close"))
        ok, notes = quality_check(f, (info.get(t) or {}).get("sector"))
        metrics = {**{k: mom.get(k) for k in PRICE_KEYS}, **{k: f.get(k) for k in FUND_KEYS}}
        cands.append({"ticker": t, "quality_pass": ok, "notes": notes, "metrics": metrics})

    score_candidates(cands, top_n)
    rows = []
    for c in cands:
        metrics = {**c["metrics"], "notes": c.get("notes", [])}
        for k in ("sector", "index"):
            if (info.get(c["ticker"]) or {}).get(k):
                metrics[k] = info[c["ticker"]][k]
        rows.append(clean({
            "as_of": as_of.isoformat(),
            "ticker": c["ticker"],
            "rank": c["rank"],
            "score": c["score"],
            "quality_pass": c["quality_pass"],
            "selected": c["selected"],
            "metrics": metrics,
        }))
    return rows
