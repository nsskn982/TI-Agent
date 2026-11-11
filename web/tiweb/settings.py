"""Settings for the TI Agent website (M9 web).

Data comes from Supabase through common.store with the service key, server-side
only: the key never reaches the browser. Django's own database (SQLite) holds
just the invite-only user accounts and sessions.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

WEB_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = WEB_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.config import env  # noqa: E402  (also loads the repo's .env)

DEBUG = (env("DJANGO_DEBUG", "false") or "false").lower() == "true"
TESTING = "pytest" in sys.modules

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY in .env (or DJANGO_DEBUG=true for local development).")

ALLOWED_HOSTS = [h.strip() for h in (env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost") or "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "tiweb.security.ContentSecurityPolicyMiddleware",
]

# "Contact" links in the header and at the end of the scroll story. Empty = hidden.
CONTACT_GITHUB_URL = env("CONTACT_GITHUB_URL", "https://github.com/nsskn982") or ""
CONTACT_LINKEDIN_URL = env("CONTACT_LINKEDIN_URL", "") or ""

ROOT_URLCONF = "tiweb.urls"
WSGI_APPLICATION = "tiweb.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "dashboard.context.contact",
        "tiweb.security.csp",
    ]},
}]

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": WEB_DIR / "db.sqlite3",
}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Feature computation hits Supabase several times; cache results briefly.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "TIMEOUT": 600}}

# Hardening for anything that isn't a local dev server.
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_AGE = 12 * 3600          # sign in again after 12 hours
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
LOGIN_MAX_FAILURES = 5                  # per username (per IP: 4x) ...
LOGIN_LOCKOUT_SECONDS = 15 * 60         # ... within this window, then HTTP 429
if not DEBUG and not TESTING:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = (env("DJANGO_SSL_REDIRECT", "true") or "true").lower() == "true"
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "3600") or 3600)
    # Behind a TLS-terminating proxy (Render, Fly, nginx) set DJANGO_BEHIND_PROXY=true.
    if (env("DJANGO_BEHIND_PROXY", "false") or "false").lower() == "true":
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"dashboard": {"handlers": ["console"], "level": "INFO"}},
}
