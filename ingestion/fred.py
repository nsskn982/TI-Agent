"""Macro series from FRED."""
from __future__ import annotations

from datetime import date

import requests

BASE = "https://api.stlouisfed.org/fred/series/observations"

DEFAULT_SERIES = (
    "DGS10",         # 10y Treasury yield
    "DGS2",          # 2y Treasury yield
    "T10Y2Y",        # 10y-2y spread
    "FEDFUNDS",      # Effective fed funds rate
    "CPIAUCSL",      # CPI
    "UNRATE",        # Unemployment rate
    "VIXCLS",        # VIX
    "BAMLH0A0HYM2",  # High-yield OAS
)


def fetch_series(session: requests.Session, series_id: str, start: date, api_key: str) -> list[dict]:
    resp = session.get(
        BASE,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
        },
    )
    resp.raise_for_status()
    return parse_observations(series_id, resp.json())


def parse_observations(series_id: str, payload: dict) -> list[dict]:
    rows = []
    for obs in payload.get("observations", []):
        value = obs.get("value")
        if value in (None, "", "."):  # FRED uses "." for missing
            continue
        rows.append({"series_id": series_id, "date": obs["date"], "value": float(value)})
    return rows
