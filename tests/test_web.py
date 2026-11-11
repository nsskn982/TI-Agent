"""Website tests: login wall, pages render real-shaped data, citations, safety."""
import pytest
from django.core.management import call_command
from django.urls import reverse

from dashboard import repo as repo_mod
from dashboard import views

RUN = {"id": 2, "as_of": "2026-11-11", "status": "ok", "model": "trading-analyst", "error": None,
       "started_at": "2026-11-11T17:21:57+00:00"}


def sug(ticker, horizon, stance="bullish", sources=("chunk_10",), thesis="Revenue grew 15.1% <script>x</script>"):
    return {"id": hash((ticker, horizon)) % 1000, "run_id": 2, "ticker": ticker, "horizon": horizon,
            "stance": stance, "thesis": thesis, "risks": ["Valuation"], "sources": list(sources),
            "confidence": 0.6, "as_of": "2026-11-11", "model": "trading-analyst"}


class FakeRepo:
    def __init__(self):
        self.suggestions = [sug("AAPL", "medium"), sug("AAPL", "long", "neutral"),
                            sug("MSFT", "medium", "bearish", sources=("chunk_10", "chunk_99"))]
        self.chunk_rows = {10: {"id": 10, "document_id": 1, "ticker": "AAPL", "source": "filing", "doc_type": "10-K",
                                "published_at": "2026-11-03T20:00:00+00:00", "content": "Greater China net sales...",
                                "title": "AAPL 10-K filed 2026-11-03", "url": "https://www.sec.gov/x.htm"},
                           11: {"id": 11, "document_id": 2, "ticker": "AAPL", "source": "news", "doc_type": "Reuters",
                                "published_at": "2026-11-05T12:00:00+00:00", "content": "Headline",
                                "title": "Bad link", "url": None}}

    def latest_good_run(self):
        return RUN

    def suggestions_for_run(self, run_id):
        return [dict(s) for s in self.suggestions]

    def ticker_suggestions(self, ticker, limit=30):
        return [dict(s) for s in self.suggestions if s["ticker"] == ticker]

    def tickers(self):
        return [{"symbol": "AAPL", "name": "Apple Inc.", "active": True}, {"symbol": "MSFT", "name": "", "active": True}]

    def chunks(self, ids):
        return {i: dict(self.chunk_rows[i]) for i in ids if i in self.chunk_rows}

    def price_history(self, ticker, days=365):
        base = 100 if ticker == "AAPL" else 400
        return [{"date": f"2026-0{m}-15", "close": base + m, "adj_close": base + m} for m in range(1, 10)]

    def features(self, ticker):
        return {"price": {"last_close": 348.51, "last_date": "2026-11-10", "ret_1m": 0.022, "rsi_14": 61.2},
                "fundamentals": {"revenue_ttm": 478834000000.0, "revenue_growth_yoy": 0.151, "period_end": "2026-09-26"},
                "sentiment": {"mean_30d": 0.12, "n_30d": 40}}

    def agent_runs(self, limit=20):
        return [RUN, {**RUN, "id": 1, "status": "error", "error": "Ollama chat failed: HTTP 500"}]

    def ingestion_runs(self, limit=40):
        return [{"job": "processing", "started_at": "2026-11-11T16:58:00+00:00", "status": "ok",
                 "counts": {"chunks": 9627}, "errors": []},
                {"job": "ingestion", "started_at": "2026-11-11T16:49:43+00:00", "status": "ok",
                 "counts": {"prices": 3306}, "errors": []}]


@pytest.fixture
def fake(monkeypatch):
    f = FakeRepo()
    monkeypatch.setattr(repo_mod, "get_repo", lambda: f)
    return f


@pytest.fixture
def user_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="alice", password="a-long-test-password")
    client.force_login(user)
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("name,args", [("home", []), ("ticker", ["AAPL"]), ("citation", [10]), ("status", [])])
def test_every_page_requires_login(client, fake, name, args):
    resp = client.get(reverse(name, args=args))
    assert resp.status_code == 302 and reverse("login") in resp["Location"]


@pytest.mark.django_db
def test_home_groups_by_ticker_and_links_citations(user_client, fake):
    html = user_client.get(reverse("home")).content.decode()
    assert "This week&#x27;s suggestions" in html or "This week's suggestions" in html
    assert html.index("AAPL") < html.index("MSFT")
    assert reverse("citation", args=[10]) in html
    assert "chunk_99" in html and 'title="Passage no longer stored"' in html  # missing citation shown, not linked
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html          # LLM text is escaped
    assert "not financial advice" in html


@pytest.mark.django_db
def test_ticker_page_chart_data_and_features(user_client, fake):
    resp = user_client.get(reverse("ticker", args=["aapl"]))
    html = resp.content.decode()
    assert resp.status_code == 200
    assert '<script id="series-data" type="application/json">' in html
    data = resp.context["series"]
    assert data["ticker"][0]["value"] == 100.0 and data["bench"][0]["value"] == 100.0  # rebased
    assert "$478.8B" in html and "+15.1%" in html
    assert "integrity=\"sha384-" in html


@pytest.mark.django_db
def test_unknown_ticker_404(user_client, fake):
    assert user_client.get(reverse("ticker", args=["TSLA"])).status_code == 404


@pytest.mark.django_db
def test_citation_page_and_unsafe_urls(user_client, fake):
    html = user_client.get(reverse("citation", args=[10])).content.decode()
    assert "Greater China net sales" in html and 'href="https://www.sec.gov/x.htm"' in html
    assert user_client.get(reverse("citation", args=[12345])).status_code == 404
    assert repo_mod.safe_url("javascript:alert(1)") is None
    assert repo_mod.safe_url("https://www.sec.gov/a") == "https://www.sec.gov/a"


@pytest.mark.django_db
def test_status_page_gates(user_client, fake):
    html = user_client.get(reverse("status")).content.decode()
    assert "1 / 7" in html and "1 / 4" in html and "Ollama chat failed" in html


def test_gate_streak_counts_only_clean_days():
    runs = [{"started_at": "2026-11-13T22:30", "status": "ok"}, {"started_at": "2026-11-12T22:30", "status": "ok"},
            {"started_at": "2026-11-12T22:40", "status": "partial"}, {"started_at": "2026-11-11T22:30", "status": "ok"}]
    assert views._consecutive_ok_days(runs) == 1


def test_chunk_id_parsing():
    assert repo_mod.chunk_ids(["chunk_1", "chunk_x", "evil", "chunk_22"]) == [1, 22]


@pytest.mark.django_db
def test_invite_command_creates_user(capsys, django_user_model):
    call_command("invite", "bob", "--email", "bob@example.com")
    out = capsys.readouterr().out
    assert "Created bob" in out and "Password (shown once)" in out
    assert django_user_model.objects.get(username="bob").has_usable_password()
