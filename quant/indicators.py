"""Technical indicators on a daily close series (pure pandas, deterministic)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252
WINDOWS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


def trailing_return(close: pd.Series, n: int) -> float | None:
    if len(close) <= n:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1)


def sma(close: pd.Series, n: int) -> float | None:
    if len(close) < n:
        return None
    return float(close.iloc[-n:].mean())


def rsi(close: pd.Series, n: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(close) <= n:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().iloc[-1]
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return float(100 - 100 / (1 + gain / loss))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    if len(close) < slow + signal:
        return None
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    return {"macd": float(line.iloc[-1]), "signal": float(sig.iloc[-1]), "hist": float(line.iloc[-1] - sig.iloc[-1])}


def volatility(close: pd.Series, n: int) -> float | None:
    """Annualised std of daily log returns over the last n days."""
    r = np.log(close).diff().dropna()
    if len(r) < n:
        return None
    return float(r.iloc[-n:].std(ddof=1) * math.sqrt(TRADING_DAYS))


def max_drawdown(close: pd.Series, n: int = TRADING_DAYS) -> float | None:
    s = close.iloc[-n:]
    if len(s) < 2:
        return None
    return float((s / s.cummax() - 1).min())


def beta(close: pd.Series, bench: pd.Series, n: int = TRADING_DAYS) -> float | None:
    joined = pd.concat([close.pct_change(), bench.pct_change()], axis=1, join="inner").dropna().iloc[-n:]
    if len(joined) < 60:
        return None
    var = joined.iloc[:, 1].var()
    if var == 0:
        return None
    return float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / var)


def price_features(close: pd.Series, bench: pd.Series | None = None) -> dict:
    """close: adjusted closes indexed by date, ascending, ending strictly before as-of."""
    close = close.dropna()
    if close.empty:
        return {}
    last = float(close.iloc[-1])
    out: dict = {"last_close": last, "last_date": close.index[-1].isoformat()[:10], "n_days": len(close)}
    for label, n in WINDOWS.items():
        out[f"ret_{label}"] = trailing_return(close, n)
    for n in (50, 200):
        m = sma(close, n)
        out[f"sma_{n}"] = m
        out[f"pct_vs_sma_{n}"] = (last / m - 1) if m else None
    out["rsi_14"] = rsi(close)
    m = macd(close)
    out.update({"macd": None, "macd_signal": None, "macd_hist": None} if m is None else
               {"macd": m["macd"], "macd_signal": m["signal"], "macd_hist": m["hist"]})
    out["vol_20d"] = volatility(close, 20)
    out["vol_60d"] = volatility(close, 60)
    out["max_drawdown_1y"] = max_drawdown(close)
    window = close.iloc[-TRADING_DAYS:]
    out["pct_from_52w_high"] = last / float(window.max()) - 1
    out["pct_from_52w_low"] = last / float(window.min()) - 1
    if bench is not None and not bench.dropna().empty:
        bench = bench.dropna()
        out["beta_1y"] = beta(close, bench)
        r, rb = trailing_return(close, 63), trailing_return(bench, 63)
        out["rel_strength_3m"] = (r - rb) if r is not None and rb is not None else None
    return out
