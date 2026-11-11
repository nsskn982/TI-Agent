from datetime import date

import pytest
from fastapi.testclient import TestClient

from processing.run import process, score_sentiment
from quant import api
from retrieval.evaluate import check
from retrieval.search import Hit, Retriever, rrf
from tests.fakes import FakeEmbedder, FakeStore


def _doc(i, ticker, source, published, title, body):
    return {"ticker": ticker, "source": source, "source_id": f"s{i}", "doc_type": "10-K" if source == "filing" else "Reuters",
            "title": title, "url": f"https://x/{i}", "published_at": published, "body": body}


@pytest.fixture
def store():
    s = FakeStore()
    s.insert_documents([
        _doc(1, "AAPL", "news", "2026-10-01T12:00:00+00:00", "iPhone sales in China slow", "Demand for iPhone fell."),
        _doc(2, "AAPL", "news", "2026-11-05T12:00:00+00:00", "Apple services hit record", "Services revenue grew."),
        _doc(3, "AAPL", "filing", "2026-10-31T20:00:00+00:00", "AAPL 10-K",
             " ".join(f"Supply chain risk {i} depends on outsourcing partners in Asia." for i in range(80))),
        _doc(4, "MSFT", "news", "2026-10-02T12:00:00+00:00", "Azure growth accelerates", "Cloud revenue up."),
        # Published after the as-of used below: must never be returned.
        _doc(5, "AAPL", "news", "2026-11-20T12:00:00+00:00", "Future iPhone China news", "Leaked from the future."),
    ])
    process(s, FakeEmbedder())
    return s


def test_rrf_rewards_agreement():
    a = [{"id": 1}, {"id": 2}, {"id": 3}]
    b = [{"id": 3}, {"id": 1}]
    fused = rrf([a, b])
    order = sorted(fused, key=lambda i: -fused[i]["score"])
    assert order == [1, 3, 2]
    assert fused[2]["ranks"] == [2, None]


def test_search_filters_ticker_and_never_looks_ahead(store):
    r = Retriever(store, FakeEmbedder())
    hits = r.search("iPhone China demand", date(2026, 11, 11), k=10, ticker="aapl")
    assert hits and all(h.ticker == "AAPL" for h in hits)
    assert all(h.published_at < "2026-11-11" for h in hits)
    assert not any("future" in h.content.lower() for h in hits)
    # Keyword side ranks the matching headline first in its list.
    top = next(h for h in hits if "iPhone sales" in h.content)
    assert top.keyword_rank == 1 and top.title == "iPhone sales in China slow"
    assert top.citation == f"chunk_{top.chunk_id}"
    # RPCs received the as-of bound and the query was ticker-prefixed for embedding.
    names = [n for n, _ in store.rpc_calls]
    assert names == ["match_chunks", "keyword_chunks"]
    assert all(p["as_of"].startswith("2026-11-11T00:00:00") for _, p in store.rpc_calls)


def test_search_limits_chunks_per_document(store):
    hits = Retriever(store, FakeEmbedder()).search("supply chain outsourcing", date(2026, 11, 11),
                                                    k=10, ticker="AAPL", source="filing", max_per_doc=2)
    assert len(hits) == 2 and {h.source for h in hits} == {"filing"}


def test_rerank_reorders(store):
    class Rev:
        def score(self, q, passages):
            return [1.0 if "Services" in p else 0.0 for p in passages]

    hits = Retriever(store, FakeEmbedder(), reranker=Rev()).search(
        "iPhone China", date(2026, 11, 11), k=3, ticker="AAPL", rerank=True)
    assert "Services" in hits[0].content and hits[0].rerank_score == 1.0


def test_recency_decay_prefers_newer(store):
    r = Retriever(store, FakeEmbedder())
    hits = r.search("Apple", date(2026, 11, 11), k=5, ticker="AAPL", source="news", recency_half_life_days=2)
    assert hits[0].published_at.startswith("2026-11-05")


def test_eval_check_flags_problems():
    h = Hit(1, 1, "AAPL", "news", None, "2026-11-12T00:00:00+00:00", "nothing relevant")
    problems = check({"ticker": "MSFT", "expect_any": ["azure"]}, [h], date(2026, 11, 11), k=2)
    assert any("LOOKAHEAD" in p for p in problems)
    assert any("wrong ticker" in p for p in problems) and any("only 1/2" in p for p in problems)


def test_sentiment_pass_scores_news_only(store):
    class Scorer:
        def score(self, texts):
            return [(0.5, "positive") for _ in texts]

    assert score_sentiment(store, Scorer()) == 4
    assert score_sentiment(store, Scorer()) == 0
    assert all(d.get("sentiment") is None for d in store.documents.values() if d["source"] == "filing")


# ------------------------------------------------------------------ API
@pytest.fixture
def client(store):
    for i, d in enumerate(__import__("pandas").bdate_range("2025-06-01", "2026-11-10")):
        for t, px in (("AAPL", 100 + i * 0.1), ("SPY", 400 + i * 0.05)):
            store.prices[(t, d.date().isoformat())] = {"ticker": t, "date": d.date().isoformat(),
                                                        "close": px, "adj_close": px, "volume": 1}
    store.macro[("DGS10", "2026-11-09")] = {"series_id": "DGS10", "date": "2026-11-09", "value": 4.1}
    api.app.dependency_overrides[api.get_store] = lambda: store
    api.app.dependency_overrides[api.get_retriever] = lambda: Retriever(store, FakeEmbedder())
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_api_features(client):
    r = client.get("/features/aapl", params={"as_of": "2026-11-11"})
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL" and body["benchmark"] == "SPY"
    assert body["price"]["last_date"] == "2026-11-10"
    assert body["price"]["ret_12m"] > 0 and body["price"]["beta_1y"] is not None
    assert set(body) >= {"fundamentals", "sentiment"}


def test_api_features_respects_as_of(client):
    body = client.get("/features/AAPL", params={"as_of": "2026-06-01"}).json()
    assert body["price"]["last_date"] < "2026-06-01"


def test_api_errors(client):
    assert client.get("/features/ZZZZ").status_code == 404
    assert client.get("/features/AAPL", params={"as_of": "2999-01-01"}).status_code == 400


def test_api_search_macro_prices(client):
    hits = client.get("/search", params={"q": "iPhone China", "ticker": "AAPL", "as_of": "2026-11-11"}).json()["hits"]
    assert hits and hits[0]["citation"].startswith("chunk_")
    assert client.get("/macro", params={"as_of": "2026-11-11"}).json()["series"]["DGS10"]["value"] == 4.1
    rows = client.get("/prices/AAPL", params={"as_of": "2026-11-11", "days": 10}).json()["rows"]
    assert 5 <= len(rows) <= 8
