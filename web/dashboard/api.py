"""Read-only JSON API for the Flutter app (served from the laptop, reached through an HTTPS tunnel).

    POST /api/login                       {"username", "password"} -> {"token", "expires_in"}
    GET  /api/runs/latest[?before=<id>]   latest good agent run (without its error text)
    GET  /api/runs/<id>/suggestions
    GET  /api/tickers/<ticker>/suggestions
    GET  /api/prices?tickers=A,B&days=365
    GET  /api/citations?ids=1,2           cited chunks only, at most 20
    GET  /api/screen/latest

Same accounts as the website (invite-only, `manage.py invite`). Login is throttled like the
web form. Every other call needs `Authorization: Bearer <token>`: a signed, expiring token
(no cookies, so no CSRF). CORS is limited to APP_ALLOWED_ORIGINS (the GitHub Pages origin).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from dashboard import repo as repo_mod
from tiweb.security import _client_ip, login_keys

SALT = "ti-agent-app-token"
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _error(message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def issue_token(user) -> str:
    return signing.dumps({"uid": user.pk}, salt=SALT)


def token_user(request):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Bearer "):
        return None
    try:
        data = signing.loads(header[7:].strip(), salt=SALT, max_age=settings.APP_TOKEN_SECONDS)
    except signing.BadSignature:  # includes SignatureExpired
        return None
    return get_user_model().objects.filter(pk=data.get("uid"), is_active=True).first()


def token_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if token_user(request) is None:
            return _error("Sign in again.", 401)
        return view(request, *args, **kwargs)

    return wrapper


def _store():
    return repo_mod.get_repo().store


def _ticker(raw: str) -> str | None:
    t = (raw or "").strip().upper()
    return t if TICKER.match(t) else None


@csrf_exempt
@require_POST
def login(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return _error("Invalid JSON.", 400)
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    keys = login_keys(_client_ip(request), username)
    limit = settings.LOGIN_MAX_FAILURES
    if any((cache.get(k) or 0) >= (limit * 4 if ":ip:" in k else limit) for k in keys):
        return _error("Too many attempts. Try again later.", 429)

    # The app's form asks for an email: accept either the username or the account's email.
    User = get_user_model()
    if "@" in username:
        match = User.objects.filter(email__iexact=username).first()
        username = match.get_username() if match else username
    user = authenticate(request, username=username, password=password) if username and password else None
    if user is None or not user.is_active:
        for k in keys:
            cache.add(k, 0, settings.LOGIN_LOCKOUT_SECONDS)
            try:
                cache.incr(k)
            except ValueError:
                cache.set(k, 1, settings.LOGIN_LOCKOUT_SECONDS)
        return _error("Invalid login credentials.", 401)
    cache.delete_many(keys)
    return JsonResponse({"token": issue_token(user), "expires_in": settings.APP_TOKEN_SECONDS})


@require_GET
@token_required
def latest_run(request):
    before = request.GET.get("before")
    if before is not None and not before.isdigit():
        return _error("before must be a run id.", 400)
    return JsonResponse({"run": _store().app_run(int(before) if before else None)})


@require_GET
@token_required
def run_suggestions(request, run_id: int):
    return JsonResponse({"rows": _store().suggestions_for_run(run_id)})


@require_GET
@token_required
def ticker_suggestions(request, ticker: str):
    t = _ticker(ticker)
    if t is None:
        return _error("Unknown ticker.", 400)
    return JsonResponse({"rows": _store().ticker_suggestions(t, 30)})


@require_GET
@token_required
def prices(request):
    tickers = [t for t in (_ticker(x) for x in request.GET.get("tickers", "").split(",")) if t][:50]
    try:
        days = min(max(int(request.GET.get("days", "365")), 1), 800)
    except ValueError:
        return _error("days must be a number.", 400)
    if not tickers:
        return JsonResponse({"rows": []})
    return JsonResponse({"rows": _store().app_prices(tickers, date.today() - timedelta(days=days))})


@require_GET
@token_required
def citations(request):
    ids = [int(x) for x in request.GET.get("ids", "").split(",") if x.strip().isdigit()][:20]
    return JsonResponse({"rows": _store().app_citations(ids) if ids else []})


@require_GET
@token_required
def latest_screen(request):
    return JsonResponse(_store().app_latest_screen())


class CorsMiddleware:
    """CORS for /api/ only, and only for the configured app origins (no cookies are involved)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        origin = request.META.get("HTTP_ORIGIN")
        allowed = origin in settings.APP_ALLOWED_ORIGINS
        if request.method == "OPTIONS" and origin:
            response = HttpResponse(status=204 if allowed else 403)
        else:
            response = self.get_response(request)
        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response["Access-Control-Max-Age"] = "3600"
            response["Vary"] = "Origin"
            response["Cross-Origin-Resource-Policy"] = "cross-origin"
        response["Cache-Control"] = "no-store"
        return response
