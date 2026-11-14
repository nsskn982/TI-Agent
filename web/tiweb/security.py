"""Security middleware and the throttled login view.

- ContentSecurityPolicyMiddleware: a strict CSP. Scripts run only from this site, the pinned
  Chart.js on cdnjs, or inline blocks carrying the per-request nonce, so text the LLM wrote
  (already HTML-escaped) still couldn't run script even if escaping ever failed.
- ThrottledLoginView: after LOGIN_MAX_FAILURES failed attempts for one username or one IP
  within LOGIN_LOCKOUT_SECONDS, further attempts get HTTP 429 until the window passes.
"""
from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.core.cache import cache
from django.shortcuts import render


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        nonce = request.csp_nonce
        policy = "; ".join([
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}' https://cdnjs.cloudflare.com",
            "style-src 'self' 'unsafe-inline'",   # style="" attributes only; no user-controlled CSS
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ])
        response.setdefault("Content-Security-Policy", policy)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response


def csp(request):
    """Template context: {{ csp_nonce }} for inline <script> tags."""
    return {"csp_nonce": getattr(request, "csp_nonce", "")}


def _client_ip(request) -> str:
    # REMOTE_ADDR only: X-Forwarded-For is client-controlled unless a trusted proxy sets it.
    # Behind the Cloudflare Tunnel every request arrives from 127.0.0.1 (cloudflared), so the
    # visitor's address comes from the CF-Connecting-IP header that cloudflared sets.
    addr = request.META.get("REMOTE_ADDR", "") or "unknown"
    if getattr(settings, "TRUST_CF_CONNECTING_IP", False) and addr in ("127.0.0.1", "::1"):
        return request.META.get("HTTP_CF_CONNECTING_IP", "").strip() or addr
    return addr


def login_keys(ip: str, username: str) -> list[str]:
    """Failure-counter cache keys, shared by the web form and the app API."""
    user = (username or "").strip().lower()
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()[:32]  # noqa: E731  (no raw usernames in cache keys)
    keys = [f"login-fail:ip:{h(ip)}"]
    if user:
        keys.append(f"login-fail:user:{h(user)}")
    return keys


def _keys(request) -> list[str]:
    return login_keys(_client_ip(request), request.POST.get("username") or "")


class ThrottledLoginView(auth_views.LoginView):
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        limit = settings.LOGIN_MAX_FAILURES
        # One username: `limit` tries. One IP (several people may share it): 4x that.
        if any((cache.get(k) or 0) >= (limit * 4 if ":ip:" in k else limit) for k in _keys(request)):
            minutes = max(1, settings.LOGIN_LOCKOUT_SECONDS // 60)
            return render(request, "registration/locked.html", {"minutes": minutes}, status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        for k in _keys(self.request):
            cache.add(k, 0, settings.LOGIN_LOCKOUT_SECONDS)
            try:
                cache.incr(k)
            except ValueError:  # expired between add and incr
                cache.set(k, 1, settings.LOGIN_LOCKOUT_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete_many(_keys(self.request))
        return super().form_valid(form)
