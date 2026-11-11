"""Company news from Finnhub (free tier: 60 calls/min, headline + summary)."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

import requests

from common.text import normalize

log = logging.getLogger(__name__)

BASE = "https://finnhub.io/api/v1"
MIN_INTERVAL_S = 1.1  # stay under 60 req/min

_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def fetch_company_news(session: requests.Session, symbol: str, start: date, end: date, token: str) -> list[dict]:
    _throttle()
    resp = session.get(
        f"{BASE}/company-news",
        params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "token": token},
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected Finnhub response for {symbol}: {str(data)[:200]}")
    return data


def to_documents(symbol: str, items: list[dict]) -> list[dict]:
    docs: dict[str, dict] = {}
    for item in items:
        headline = normalize(item.get("headline") or "")
        summary = normalize(item.get("summary") or "")
        ts = item.get("datetime")
        if not headline or not ts:
            continue
        source_id = f"finnhub:{item.get('id') or item.get('url')}"
        if source_id in docs:  # keep the first (most complete) copy
            continue
        docs[source_id] = {
            "ticker": symbol,
            "source": "news",
            "source_id": source_id,
            "doc_type": item.get("source") or "news",
            "title": headline[:500],
            "url": item.get("url"),
            "published_at": datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(),
            "body": summary,
            "meta": {"category": item.get("category"), "related": item.get("related")},
        }
    return list(docs.values())
