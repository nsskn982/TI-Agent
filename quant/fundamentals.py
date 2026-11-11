"""Point-in-time fundamentals from as-reported XBRL facts.

Only facts filed before the as-of date are used, and for each period the most
recent filing (restatement) known at that time wins. Quarterly values are
derived from year-to-date chains (Q2 = H1 - Q1, Q4 = FY - 9M), because cash-flow
statements are usually reported YTD only.
"""
from __future__ import annotations

from datetime import date, timedelta

from ingestion.fundamentals import METRICS

QUARTER_DAYS = (75, 119)  # 12-17 week fiscal quarters (Costco's Q4 is 16 weeks)
# Units we accept per metric family; anything else (other currencies) is ignored.
UNITS = {"USD", "USD/shares", "shares"}


def _d(s: str | date) -> date:
    return s if isinstance(s, date) else date.fromisoformat(str(s)[:10])


def point_in_time(facts: list[dict], concepts: list[str], as_of: date) -> dict[tuple[date, date], float]:
    """{(start, end): value}, merging concepts by priority, latest filing per period."""
    by_period: dict[tuple[date, date], tuple[int, date, float]] = {}
    priority = {c: i for i, c in enumerate(concepts)}
    for f in facts:
        if f["concept"] not in priority or f["unit"] not in UNITS:
            continue
        filed = _d(f["filed"])
        if filed >= as_of:
            continue
        key = (_d(f["period_start"]), _d(f["period_end"]))
        cand = (priority[f["concept"]], filed, float(f["value"]))
        cur = by_period.get(key)
        # Lower priority index wins; within a concept, the later filing wins.
        if cur is None or cand[0] < cur[0] or (cand[0] == cur[0] and cand[1] > cur[1]):
            by_period[key] = cand
    return {k: v[2] for k, v in by_period.items()}


def quarterly(periods: dict[tuple[date, date], float]) -> dict[date, float]:
    """Discrete ~3-month values keyed by period end."""
    out: dict[date, float] = {}
    lo, hi = QUARTER_DAYS
    for (s, e), v in periods.items():
        if lo <= (e - s).days <= hi:
            out[e] = v
    # YTD chains share a start date: consecutive differences are quarters.
    chains: dict[date, list[tuple[date, float]]] = {}
    for (s, e), v in periods.items():
        if (e - s).days > lo:
            chains.setdefault(s, []).append((e, v))
    for s, items in chains.items():
        items.sort()
        items.insert(0, (s - timedelta(days=1), 0.0))
        for (e1, v1), (e2, v2) in zip(items, items[1:]):
            if lo <= (e2 - e1).days <= hi and e2 not in out:
                out[e2] = v2 - v1
    return out


def ttm(quarters: dict[date, float], as_of_end: date | None = None) -> tuple[float, date] | None:
    """Sum of the last 4 consecutive quarters ending on/before as_of_end."""
    ends = sorted(e for e in quarters if as_of_end is None or e <= as_of_end)
    if len(ends) < 4:
        return None
    last4 = ends[-4:]
    span = (last4[-1] - last4[0]).days
    if not 250 <= span <= 300:  # 3 quarter-gaps ~ 273 days; reject holes
        return None
    return sum(quarters[e] for e in last4), last4[-1]


def latest_instant(periods: dict[tuple[date, date], float]) -> tuple[float, date] | None:
    inst = [(e, v) for (s, e), v in periods.items() if s == e]
    if not inst:
        return None
    e, v = max(inst)
    return v, e


def fundamental_features(facts: list[dict], as_of: date, last_close: float | None) -> dict:
    flows: dict[str, tuple[float, date] | None] = {}
    flows_prev: dict[str, tuple[float, date] | None] = {}
    for metric, (kind, concepts) in METRICS.items():
        if kind != "flow":
            continue
        q = quarterly(point_in_time(facts, concepts, as_of))
        cur = ttm(q)
        flows[metric] = cur
        flows_prev[metric] = ttm(q, cur[1] - timedelta(days=330)) if cur else None

    inst = {
        m: latest_instant(point_in_time(facts, concepts, as_of))
        for m, (kind, concepts) in METRICS.items()
        if kind == "instant"
    }

    def val(d, k):
        x = d.get(k)
        return x[0] if x else None

    rev, rev_prev = val(flows, "revenue"), val(flows_prev, "revenue")
    eps = val(flows, "eps_diluted")
    cfo, capex = val(flows, "cfo"), val(flows, "capex")
    shares, equity, debt = val(inst, "shares_outstanding"), val(inst, "equity"), val(inst, "long_term_debt")
    fcf = cfo - capex if cfo is not None and capex is not None else None
    mcap = last_close * shares if last_close and shares else None

    def ratio(a, b, positive_b=True):
        if a is None or b is None or b == 0 or (positive_b and b < 0):
            return None
        return a / b

    period_end = flows["revenue"][1] if flows.get("revenue") else None
    stale = period_end is not None and (as_of - period_end).days > 200
    return {
        "period_end": period_end.isoformat() if period_end else None,
        "stale": stale,
        "revenue_ttm": rev,
        "revenue_growth_yoy": (rev / rev_prev - 1) if rev and rev_prev else None,
        "gross_margin": ratio(val(flows, "gross_profit"), rev),
        "operating_margin": ratio(val(flows, "operating_income"), rev),
        "net_margin": ratio(val(flows, "net_income"), rev),
        "eps_ttm": eps,
        "pe_ttm": ratio(last_close, eps) if eps and eps > 0 else None,
        "fcf_ttm": fcf,
        "fcf_yield": ratio(fcf, mcap),
        "market_cap": mcap,
        "debt_to_equity": ratio(debt, equity),
        "cash": val(inst, "cash"),
    }
