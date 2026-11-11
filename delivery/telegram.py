"""Telegram delivery (M9): weekly digest and failure alerts via the Bot API."""
from __future__ import annotations

import logging

import requests

from common.config import env

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 4000  # Telegram's hard limit is 4096 characters
STANCE_MARK = {"bullish": "▲", "neutral": "■", "bearish": "▼"}
DISCLAIMER = "Research output, not financial advice. TI Agent never trades."


def format_digest(as_of: str, results: list, failures: dict[str, str]) -> str:
    lines = [f"TI Agent weekly views, as of {as_of}", ""]
    for r in results:
        if not r.saved:
            continue
        lines.append(r.ticker)
        for horizon in ("medium", "long"):
            s = r.saved.get(horizon)
            if not s:
                continue
            label = "1-3m" if horizon == "medium" else "6-24m"
            lines.append(f"  {STANCE_MARK[s['stance']]} {label}: {s['stance']} "
                         f"(confidence {s['confidence']:.2f})")
            lines.append(f"    {s['thesis']}")
            if s.get("risks"):
                lines.append(f"    Risks: {'; '.join(s['risks'])}")
        lines.append("")
    if failures:
        lines.append("Not completed: " + ", ".join(f"{t} ({e})" for t, e in failures.items()))
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Split on line boundaries so no message exceeds Telegram's limit."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single giant line
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts


def send(text: str, token: str | None = None, chat_id: str | None = None,
         session: requests.Session | None = None) -> bool:
    token = token or env("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); skipping send")
        return False
    session = session or requests.Session()
    for part in split_message(text):
        try:
            resp = session.post(API.format(token=token), json={
                "chat_id": chat_id, "text": part, "disable_web_page_preview": True}, timeout=30)
        except requests.RequestException as exc:
            # requests puts the URL (and so the bot token) in its messages: log only the type.
            log.error("Telegram send failed: %s (network error)", type(exc).__name__)
            return False
        if resp.status_code != 200:
            # Never log the URL: it contains the bot token.
            log.error("Telegram send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
    return True
