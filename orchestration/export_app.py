"""Export what the app shows to site-data/data.json, encrypted with APP_DATA_PASSWORD.

    python -m orchestration.export_app            # also runs at the end of every daily, screen and AI run
    python -m orchestration.export_app --check    # decrypt the current file and print what's in it

The Flutter app on GitHub Pages downloads this one file and decrypts it in the browser with the
password, so the site needs no server, tunnel or domain. GitHub Pages is public: without the
password the file is unreadable, but anyone can download it and try passwords offline, so use a
long random one (see .env.example). Push site-data/ after a run to publish new data.

Format (all base64): {"v", "kdf": "pbkdf2-sha256", "iter", "salt", "iv", "ct"} where ct is the
AES-256-GCM ciphertext with its 16-byte tag appended (what the Dart `cryptography` package reads).
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from common import logging_setup, progress
from common.config import ROOT, benchmark, env

log = logging.getLogger("export_app")

OUT = ROOT / "site-data" / "data.json"
FORMAT_VERSION = 1
ITERATIONS = 250_000      # PBKDF2-SHA256; the browser's Web Crypto does this in well under a second
MIN_PASSWORD = 12
PRICE_DAYS = 370          # the app's ticker chart shows 12 months
HISTORY = 30              # suggestions per ticker on the ticker page


# ------------------------------------------------------------------ crypto
def _key(password: str, salt: bytes, iterations: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(password.encode())


def encrypt(plain: bytes, password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = salt or os.urandom(16)
    iv = os.urandom(12)  # fresh for every encryption, so a reused salt (same key) stays safe
    ct = AESGCM(_key(password, salt, iterations)).encrypt(iv, plain, None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"v": FORMAT_VERSION, "kdf": "pbkdf2-sha256", "iter": iterations, "salt": b64(salt), "iv": b64(iv),
            "ct": b64(ct)}


def decrypt(doc: dict, password: str) -> bytes:
    """Raises cryptography.exceptions.InvalidTag on a wrong password or a damaged file."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, iv, ct = (base64.b64decode(doc[k]) for k in ("salt", "iv", "ct"))
    return AESGCM(_key(password, salt, int(doc["iter"]))).decrypt(iv, ct, None)


# ------------------------------------------------------------------ what the app shows
def build_bundle(store, today: date | None = None) -> dict:
    today = today or date.today()
    run = store.app_run()
    prev = store.app_run(run["id"]) if run else None
    suggestions = {str(r["id"]): store.suggestions_for_run(r["id"]) for r in (run, prev) if r}

    screen = store.app_latest_screen()
    picks = [r for r in screen["rows"] if r.get("selected") and r.get("rank") is not None]
    tickers = sorted({r["ticker"] for r in picks} | {s["ticker"] for rows in suggestions.values() for s in rows})
    history = {t: store.ticker_suggestions(t, HISTORY) for t in tickers}

    bench = benchmark()
    prices: dict[str, list] = {}
    for r in store.app_prices(tickers + [bench], today - timedelta(days=PRICE_DAYS)):
        prices.setdefault(r["ticker"], []).append(
            [r["date"], _round(r.get("close")), _round(r.get("adj_close"))])

    ids = sorted({int(s[6:]) for rows in [*suggestions.values(), *history.values()] for row in rows
                  for s in row.get("sources") or [] if s.startswith("chunk_") and s[6:].isdigit()})
    citations = {}
    for i in range(0, len(ids), 20):  # app_citations returns at most 20 per call
        for c in store.app_citations(ids[i:i + 20]):
            citations[str(c["id"])] = c

    return {
        "runs": [r for r in (run, prev) if r],
        "suggestions": suggestions,
        "history": history,
        "screen": {"as_of": screen.get("as_of"), "screened": len(screen["rows"]), "picks": picks},
        "prices": prices,
        "citations": citations,
        "benchmark": bench,
    }


def _round(v):
    return None if v is None else round(float(v), 4)


# ------------------------------------------------------------------ write
def export(store, password: str, out: Path = OUT, iterations: int = ITERATIONS) -> str:
    """Writes the file if its contents changed. Returns 'written', 'unchanged' or 'new password'."""
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"APP_DATA_PASSWORD must be at least {MIN_PASSWORD} characters")
    bundle = build_bundle(store)
    body = json.dumps(bundle, sort_keys=True, separators=(",", ":"), default=str)

    salt, outcome = None, "written"
    if out.exists():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
            old_plain = json.loads(decrypt(old, password))
            # Same password: keep the salt so devices that remember the key keep working.
            salt = base64.b64decode(old["salt"])
            if int(old.get("iter", 0)) != iterations:
                salt = None
            elif json.dumps(old_plain.get("data"), sort_keys=True, separators=(",", ":"), default=str) == body:
                return "unchanged"
        except Exception:  # different password (or an unreadable file): start over with a new salt
            outcome = "new password"
    payload = json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "data": bundle}, separators=(",", ":"), default=str).encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(encrypt(payload, password, salt, iterations)), encoding="utf-8")
    tmp.replace(out)
    return outcome


def export_if_configured(store) -> str:
    """The run scripts call this last. Without a password the app simply gets no new data."""
    password = env("APP_DATA_PASSWORD")
    if not password:
        progress.skip("Export app data", "APP_DATA_PASSWORD not set")
        log.warning("APP_DATA_PASSWORD is not set in .env: app data not exported")
        return "skipped"
    with progress.step("Export app data") as st:
        outcome = export(store, password)
        st.set_result({"written": "site-data/data.json updated · push it to publish",
                       "unchanged": "no changes",
                       "new password": "re-encrypted with the new password · push it"}[outcome])
    log.info("App data export: %s (%s)", outcome, OUT)
    return outcome


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description="Export the app's data, encrypted, to site-data/data.json")
    p.add_argument("--check", action="store_true", help="Decrypt the current file and summarise it")
    args = p.parse_args(argv)
    password = env("APP_DATA_PASSWORD")
    if not password:
        log.error("Set APP_DATA_PASSWORD in .env first (a long random password; see .env.example)")
        return 2
    if args.check:
        doc = json.loads(OUT.read_text(encoding="utf-8"))
        data = json.loads(decrypt(doc, password))
        d = data["data"]
        print(f"generated {data['generated_at']} · {len(d['screen']['picks'])} picks · "
              f"{sum(len(v) for v in d['suggestions'].values())} suggestions · {len(d['citations'])} citations · "
              f"{sum(len(v) for v in d['prices'].values())} price rows · {OUT.stat().st_size / 1024:.0f} KB")
        return 0
    from common.store import Store

    with progress.workflow("Export app data", ["Export app data"]):
        export_if_configured(Store())
    return 0


if __name__ == "__main__":
    sys.exit(main())
