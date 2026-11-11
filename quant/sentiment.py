"""Aggregate per-headline FinBERT scores into ticker-level features."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd


def sentiment_features(rows: list[dict], as_of: date) -> dict:
    """rows: [{"published_at", "sentiment"}] with published_at < as_of, last ~90 days."""
    end = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)
    if not rows:
        return {"n_7d": 0, "n_30d": 0, "n_90d": 0, "mean_7d": None, "mean_30d": None, "mean_90d": None,
                "trend_7d_vs_30d": None, "pos_share_30d": None, "news_volume_z": None}
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["published_at"], utc=True)
    df = df[df["ts"] < end]
    age = (end - df["ts"]).dt.total_seconds() / 86400

    def window(days):
        return df.loc[age < days, "sentiment"].astype(float)

    w7, w30, w90 = window(7), window(30), window(90)
    mean = lambda s: float(s.mean()) if len(s) else None  # noqa: E731

    # News-volume spike: this week's headline count vs the trailing 12 weekly counts.
    weeks = (age // 7).astype(int)
    weekly = weeks[weeks < 13].value_counts().reindex(range(13), fill_value=0)
    hist = weekly.iloc[1:]
    z = float((weekly.iloc[0] - hist.mean()) / hist.std()) if hist.std() > 0 else None

    m7, m30 = mean(w7), mean(w30)
    return {
        "n_7d": int(len(w7)),
        "n_30d": int(len(w30)),
        "n_90d": int(len(w90)),
        "mean_7d": m7,
        "mean_30d": m30,
        "mean_90d": mean(w90),
        "trend_7d_vs_30d": (m7 - m30) if m7 is not None and m30 is not None else None,
        "pos_share_30d": float((w30 > 0.2).mean()) if len(w30) else None,
        "news_volume_z": z,
    }


def window_start(as_of: date) -> date:
    return as_of - timedelta(days=91)
