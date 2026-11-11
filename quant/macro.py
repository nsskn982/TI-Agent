"""Macro snapshot as of a date, respecting publication lags.

FRED dates are *observation* dates, not release dates: October CPI is dated
2026-10-01 but published mid-November. Using it on 2026-10-02 would be
lookahead, so each series only counts once `date + lag` has passed.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ingestion.fred import DEFAULT_SERIES

# Conservative days from observation date to public release.
RELEASE_LAG_DAYS = {
    "DGS10": 1, "DGS2": 1, "T10Y2Y": 1, "VIXCLS": 1, "BAMLH0A0HYM2": 1,
    "FEDFUNDS": 35, "UNRATE": 40, "CPIAUCSL": 45,
}
LOOKBACK_DAYS = 500


def macro_features(rows: list[dict], as_of: date) -> dict:
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    out: dict = {}
    for sid in DEFAULT_SERIES:
        lag = RELEASE_LAG_DAYS.get(sid, 45)
        s = df[(df["series_id"] == sid) & (df["date"] <= as_of - timedelta(days=lag))].sort_values("date")
        if s.empty:
            continue
        last_date, last = s["date"].iloc[-1], float(s["value"].iloc[-1])

        def value_at(d):
            prior = s[s["date"] <= d]
            return float(prior["value"].iloc[-1]) if not prior.empty else None

        entry = {"value": last, "date": last_date.isoformat()}
        for label, days in (("1m", 30), ("3m", 91)):
            prev = value_at(last_date - timedelta(days=days))
            entry[f"change_{label}"] = (last - prev) if prev is not None else None
        if sid == "CPIAUCSL":
            prev = value_at(last_date - timedelta(days=365))
            entry["yoy"] = (last / prev - 1) if prev else None
        out[sid] = entry
    return out
