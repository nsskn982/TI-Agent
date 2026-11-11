"""Daily OHLCV from yfinance."""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta

import pandas as pd

log = logging.getLogger(__name__)


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def frame_to_rows(symbol: str, df: pd.DataFrame) -> list[dict]:
    rows = []
    if df is None or df.empty:
        return rows
    for idx, r in df.iterrows():
        close = _num(r.get("Close"))
        if close is None:
            continue
        vol = _num(r.get("Volume"))
        rows.append(
            {
                "ticker": symbol,
                "date": pd.Timestamp(idx).date().isoformat(),
                "open": _num(r.get("Open")),
                "high": _num(r.get("High")),
                "low": _num(r.get("Low")),
                "close": close,
                "adj_close": _num(r.get("Adj Close")) or close,
                "volume": int(vol) if vol is not None else None,
            }
        )
    return rows


def fetch_prices(symbol: str, start: date, end: date | None = None) -> list[dict]:
    import yfinance as yf

    end = end or date.today() + timedelta(days=1)
    df = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False, actions=False)
    return frame_to_rows(symbol, df)
