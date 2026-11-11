"""Security fixes: CSP nonce, login throttling, admin login route, API access, token-safe logs."""
import logging
import re

import pytest
import requests
from django.core.cache import cache
from django.urls import reverse
from fastapi.testclient import TestClient

from delivery import telegram
from quant import api


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_csp_header_and_every_inline_script_has_the_nonce(client):
    resp = client.get(reverse("login"))
    csp = resp["Content-Security-Policy"]
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert "object-src 'none'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp.split("style-src")[0]
    html = resp.content.decode()
    scripts = re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)([^>]*)>", html)
    assert scripts and all(f'nonce="{nonce}"' in attrs for attrs in scripts)
    assert client.get(reverse("login"))["Content-Security-Policy"] != csp  # fresh nonce per request
    assert "camera=()" in resp["Permissions-Policy"]


@pytest.mark.django_db
def test_login_locks_after_repeated_failures(client, django_user_model, settings):
    django_user_model.objects.create_user(username="alice", password="a-long-test-password")
    for _ in range(settings.LOGIN_MAX_FAILURES):
        assert client.post(reverse("login"), {"username": "alice", "password": "wrong"}).status_code == 200
    locked = client.post(reverse("login"), {"username": "alice", "password": "a-long-test-password"})
    assert locked.status_code == 429 and b"Too many sign-in attempts" in locked.content


@pytest.mark.django_db
def test_successful_login_resets_counter(client, django_user_model, settings):
    django_user_model.objects.create_user(username="bob", password="a-long-test-password")
    for _ in range(settings.LOGIN_MAX_FAILURES - 1):
        client.post(reverse("login"), {"username": "bob", "password": "wrong"})
    assert client.post(reverse("login"), {"username": "bob", "password": "a-long-test-password"}).status_code == 302
    client.logout()
    assert client.post(reverse("login"), {"username": "bob", "password": "wrong"}).status_code == 200


@pytest.mark.django_db
def test_admin_login_goes_through_throttled_login(client):
    resp = client.get("/admin/login/?next=/admin/")
    assert resp.status_code in (301, 302) and resp["Location"].startswith(reverse("login"))


def test_api_rejects_remote_clients_without_token(monkeypatch):
    monkeypatch.delenv("QUANT_API_TOKEN", raising=False)
    remote = TestClient(api.app, client=("203.0.113.9", 5555))
    assert remote.get("/health").status_code == 403
    assert TestClient(api.app).get("/health").status_code == 200  # local test client


def test_api_requires_bearer_token_when_set(monkeypatch):
    monkeypatch.setenv("QUANT_API_TOKEN", "s3cret-token")
    c = TestClient(api.app)
    assert c.get("/health").status_code == 401
    assert c.get("/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/health", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_telegram_network_error_never_logs_token(caplog):
    class Boom:
        def post(self, url, **kw):
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
    with caplog.at_level(logging.ERROR):
        assert telegram.send("hi", token="123456:SECRET-TOKEN", chat_id="1", session=Boom()) is False
    assert "SECRET-TOKEN" not in caplog.text and "ConnectionError" in caplog.text
