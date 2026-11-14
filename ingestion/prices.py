"""Daily OHLCV from yfinance."""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta

import pandas as pd

from common import progress

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


def split_download(df: pd.DataFrame, symbols: list[str]) -> dict[str, list[dict]]:
    """Rows per symbol from a multi-ticker yf.download frame (columns: (symbol, field))."""
    out: dict[str, list[dict]] = {}
    if df is None or df.empty:
        return out
    if not isinstance(df.columns, pd.MultiIndex):  # a single symbol comes back flat
        return {symbols[0]: frame_to_rows(symbols[0], df)} if len(symbols) == 1 else out
    level0 = set(df.columns.get_level_values(0))
    for s in symbols:
        if s in level0:
            rows = frame_to_rows(s, df[s].dropna(how="all"))
            if rows:
                out[s] = rows
    return out


def fetch_many(symbols: list[str], start: date, end: date | None = None, chunk: int = 100) -> dict[str, list[dict]]:
    """Daily bars for many symbols, downloaded in chunks (one request per chunk, not per ticker).
    Symbols that come back empty are retried one by one."""
    import yfinance as yf

    end = end or date.today() + timedelta(days=1)
    out: dict[str, list[dict]] = {}
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        progress.current_step().set_note(f"batch {i // chunk + 1} of {(len(symbols) + chunk - 1) // chunk}")
        try:
            df = yf.download(part, start=start.isoformat(), end=end.isoformat(), auto_adjust=False,
                             actions=False, group_by="ticker", threads=True, progress=False)
            out.update(split_download(df, part))
        except Exception as exc:
            log.warning("batch download failed for %d symbols (%s); retrying one by one", len(part), exc)
        progress.current_step().advance(len(part))
    for s in symbols:
        if s not in out:
            try:
                rows = fetch_prices(s, start, end)
                if rows:
                    out[s] = rows
            except Exception as exc:
                log.warning("prices for %s failed: %s", s, exc)
    return out


def fetch_prices(symbol: str, start: date, end: date | None = None) -> list[dict]:
    import yfinance as yf

    end = end or date.today() + timedelta(days=1)
    df = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False, actions=False)
    return frame_to_rows(symbol, df)
