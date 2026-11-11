"""Shared HTTP session with retries/backoff for the free-tier APIs."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 30


class _TimeoutSession(requests.Session):
    def request(self, *args, **kwargs):  # type: ignore[override]
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        return super().request(*args, **kwargs)


def make_session(user_agent: str = "TI-Agent/0.1", retries: int = 4) -> requests.Session:
    session = _TimeoutSession()
    retry = Retry(
        total=retries,
        backoff_factor=1.5,  # 0, 1.5, 3, 6 ... seconds
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    return session
