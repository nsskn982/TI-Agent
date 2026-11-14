"""Realised outcomes: excess return over the benchmark after h trading days.

Entry is the first trading day on or after the view's as-of date (the view uses data strictly before
as_of, so the earliest it could be acted on is that day's close). Exit is h trading days later, on
the dates both the stock and the benchmark traded. Adjusted closes, so dividends and splits count.
"""
from __future__ import annotations

from datetime import date
from typing import Sequence

HORIZONS = (21, 63, 252)          # about 1, 3 and 12 months of trading days
HORIZON_OF_VIEW = {"medium": 63, "long": 252}   # the horizon each view is about (primary analysis)


def forward_excess(stock: Sequence[tuple[str, float]], bench: dict[str, float], as_of: date | str,
                   h: int) -> dict | None:
    """Excess return h trading days after as_of, or None while the window hasn't closed yet."""
    start = as_of if isinstance(as_of, str) else as_of.isoformat()
    days = [(d, p) for d, p in stock if d in bench and d >= start[:10]]
    if len(days) <= h:
        return None
    (d0, p0), (d1, p1) = days[0], days[h]
    b0, b1 = bench[d0], bench[d1]
    if p0 <= 0 or b0 <= 0:
        return None
    r, rb = p1 / p0 - 1.0, b1 / b0 - 1.0
    return {"entry_date": d0, "exit_date": d1, "ticker_return": r, "benchmark_return": rb, "excess_return": r - rb}


def hit(stance: str, excess: float) -> bool | None:
    """Whether a relative stance was right: bullish beat the benchmark, bearish lagged it.
    Neutral views have no direction, so they are left out of hit rates."""
    if stance == "bullish":
        return excess > 0
    if stance == "bearish":
        return excess < 0
    return None
