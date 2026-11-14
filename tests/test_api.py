"""App API: token login, throttling, auth wall, CORS, input validation, no error text."""
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from dashboard import repo as repo_mod

ORIGIN = "https://nsskn982.github.io"


class FakeStore:
    def __init__(self):
        self.calls = []

    def app_run(self, before_id=None):
        self.calls.append(("run", before_id))
        return {"id": 2, "as_of": "2026-11-14", "status": "ok", "model": "m"}

    def suggestions_for_run(self, run_id):
        return [{"id": 1, "run_id": run_id, "ticker": "AAPL", "horizon": "long", "stance": "bullish"}]

    def ticker_suggestions(self, ticker, limit=30):
        self.calls.append(("ticker", ticker))
        return []

    def app_prices(self, tickers, since):
        self.calls.append(("prices", tuple(tickers)))
        return [{"ticker": "AAPL", "date": "2026-11-13", "close": 1.0, "adj_close": 1.0}]

    def app_citations(self, ids):
        self.calls.append(("citations", tuple(ids)))
        return []

    def app_latest_screen(self):
        return {"as_of": "2026-11-15", "rows": []}


@pytest.fixture
def store(monkeypatch):
    cache.clear()
    s = FakeStore()
    monkeypatch.setattr(repo_mod, "get_repo", lambda: type("R", (), {"store": s})())
    yield s
    cache.clear()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("alice", "alice@example.com", "a-long-test-password")


def _login(client, username="alice", password="a-long-test-password"):
    return client.post("/api/login", json.dumps({"username": username, "password": password}),
                       content_type="application/json")


def test_login_with_username_or_email_then_read(client, store, user):
    assert _login(client, "alice@example.com").status_code == 200
    token = _login(client).json()["token"]
    r = client.get("/api/runs/latest", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 200 and r.json()["run"]["id"] == 2 and "error" not in r.json()["run"]
    r = client.get("/api/prices?tickers=aapl,bad ticker,<x>&days=99999", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 200 and ("prices", ("AAPL",)) in store.calls
    client.get("/api/citations?ids=1,x,2," + ",".join(map(str, range(3, 40))), HTTP_AUTHORIZATION=f"Bearer {token}")
    assert len(next(c for c in store.calls if c[0] == "citations")[1]) == 20


def test_everything_needs_a_valid_token(client, store, user):
    for url in ("/api/runs/latest", "/api/runs/2/suggestions", "/api/tickers/AAPL/suggestions",
                "/api/prices?tickers=AAPL", "/api/citations?ids=1", "/api/screen/latest"):
        assert client.get(url).status_code == 401
        assert client.get(url, HTTP_AUTHORIZATION="Bearer forged.token").status_code == 401
    user.is_active = False
    user.save()
    assert _login(client).status_code == 401


def test_login_is_throttled(client, store, user, settings):
    for _ in range(settings.LOGIN_MAX_FAILURES):
        assert _login(client, password="wrong").status_code == 401
    assert _login(client).status_code == 429


def test_cors_only_for_the_app_origin(client, store, user):
    r = client.options("/api/runs/latest", HTTP_ORIGIN=ORIGIN, HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET")
    assert r.status_code == 204 and r["Access-Control-Allow-Origin"] == ORIGIN
    assert "Authorization" in r["Access-Control-Allow-Headers"]
    r = client.options("/api/runs/latest", HTTP_ORIGIN="https://evil.example")
    assert r.status_code == 403 and "Access-Control-Allow-Origin" not in r
    assert "Access-Control-Allow-Origin" not in client.get("/login/", HTTP_ORIGIN=ORIGIN)


def test_throttle_uses_cloudflare_client_ip_only_when_trusted(rf, settings):
    from tiweb.security import _client_ip

    req = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="203.0.113.9")
    settings.TRUST_CF_CONNECTING_IP = False
    assert _client_ip(req) == "127.0.0.1"
    settings.TRUST_CF_CONNECTING_IP = True
    assert _client_ip(req) == "203.0.113.9"
    # a direct (non-tunnel) client can't spoof the header
    assert _client_ip(rf.get("/", REMOTE_ADDR="198.51.100.7", HTTP_CF_CONNECTING_IP="1.2.3.4")) == "198.51.100.7"
