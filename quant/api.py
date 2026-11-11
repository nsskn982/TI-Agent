"""M4/M5 local API. The Phase 3 agent tools are thin wrappers over these routes.

    uvicorn quant.api:app --port 8000
    open http://localhost:8000/docs
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query

from quant import features

app = FastAPI(title="TI Agent quant + retrieval", version="0.2.0")


@lru_cache(maxsize=1)
def get_store():
    from common.store import Store

    return Store()


@lru_cache(maxsize=1)
def get_retriever():
    from processing.embed import Embedder
    from retrieval.search import Retriever

    return Retriever(get_store(), Embedder())


def _as_of(as_of: date | None) -> date:
    as_of = as_of or date.today()
    if as_of > date.today():
        raise HTTPException(400, "as_of cannot be in the future")
    return as_of


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/features/{ticker}")
def get_features(ticker: str, as_of: date | None = None, store=Depends(get_store)):
    """Technicals, point-in-time fundamentals and news sentiment, all strictly before as_of."""
    out = features.compute_features(store, ticker, _as_of(as_of))
    if not out["price"]:
        raise HTTPException(404, f"No price history for {ticker.upper()} before {out['as_of']}")
    return out


@app.get("/prices/{ticker}")
def get_prices(ticker: str, as_of: date | None = None, days: int = Query(180, ge=1, le=800),
               store=Depends(get_store)):
    as_of = _as_of(as_of)
    rows = features.get_prices(store, ticker.upper(), as_of, days)
    return {"ticker": ticker.upper(), "as_of": as_of.isoformat(), "rows": rows}


@app.get("/macro")
def get_macro(as_of: date | None = None, store=Depends(get_store)):
    return features.compute_macro(store, _as_of(as_of))


@app.get("/search")
def search(
    q: str = Query(..., min_length=2),
    ticker: str | None = None,
    source: Literal["news", "filing"] | None = None,
    as_of: date | None = None,
    k: int = Query(8, ge=1, le=30),
    rerank: bool = False,
    recency_half_life_days: float | None = Query(None, gt=0),
    retriever=Depends(get_retriever),
):
    as_of = _as_of(as_of)
    hits = retriever.search(q, as_of, k=k, ticker=ticker, source=source, rerank=rerank,
                            recency_half_life_days=recency_half_life_days)
    return {"query": q, "as_of": as_of.isoformat(), "hits": [h.to_dict() for h in hits]}
