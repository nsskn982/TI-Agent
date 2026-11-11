"""Assemble the per-ticker feature set the agent sees (via get_features)."""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from common.config import benchmark
from ingestion.fred import DEFAULT_SERIES
from quant import fundamentals, indicators, macro, sentiment

PRICE_LOOKBACK_DAYS = 400  # ~252 trading days + slack


def clean(obj, digits: int = 6):
    """Make output JSON-safe: NaN/inf -> None, floats rounded."""
    if isinstance(obj, dict):
        return {k: clean(v, digits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v, digits) for v in obj]
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, digits)
    return obj


def close_series(rows: list[dict]) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    px = df["adj_close"].fillna(df["close"]).astype(float)
    return pd.Series(px.values, index=pd.to_datetime(df["date"]), name="close").sort_index()


def get_prices(store, ticker: str, as_of: date, days: int = PRICE_LOOKBACK_DAYS) -> list[dict]:
    return store.get_prices(ticker, as_of - timedelta(days=days), as_of)


def compute_features(store, ticker: str, as_of: date) -> dict:
    ticker = ticker.upper()
    close = close_series(get_prices(store, ticker, as_of))
    bench_t = benchmark()
    bench = close_series(get_prices(store, bench_t, as_of)) if bench_t != ticker else None
    price = indicators.price_features(close, bench)
    facts = store.get_fundamentals(ticker, as_of)
    news = store.get_news_sentiment(ticker, sentiment.window_start(as_of), as_of)
    return clean({
        "ticker": ticker,
        "as_of": as_of.isoformat(),
        "benchmark": bench_t,
        "price": price,
        "fundamentals": fundamentals.fundamental_features(facts, as_of, price.get("last_close")),
        "sentiment": sentiment.sentiment_features(news, as_of),
    })


def compute_macro(store, as_of: date) -> dict:
    rows = store.get_macro(DEFAULT_SERIES, as_of - timedelta(days=macro.LOOKBACK_DAYS), as_of)
    return clean({"as_of": as_of.isoformat(), "series": macro.macro_features(rows, as_of)})
