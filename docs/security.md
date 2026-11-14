# Security

*Review date: 2026-11-11.* What TI Agent protects, how, what the review found and fixed, and what you
still need to set up yourself.

## What we protect

| Asset | Why it matters | Where it lives |
|---|---|---|
| Local database (PostgreSQL) | Full read and write of all data | Docker on the laptop, listening on 127.0.0.1:5433 only. Password in `.env`; never in git or the app |
| API keys (Finnhub, FRED), Telegram bot token | Abuse of free quotas; posting as the bot | `.env` on the laptop |
| Suggestions | Publishing investment recommendations may fall under EU market rules (MAR) | Local database; in the app only inside the password-encrypted data file |
| Website accounts, app password | Access to the above | Django's SQLite (local dashboard); `APP_DATA_PASSWORD` in `.env` |

## How each part is protected

**Database (local PostgreSQL).**
- The container binds to `127.0.0.1` only, so other machines on the network can't connect. Only processes
  on the laptop (the pipeline and the dashboard) use it.
- `Store.rpc()` calls only the known search functions; everything else is plain SQL with bound parameters.

**App data on GitHub Pages (`site-data/data.json`).**
- GitHub Pages is public, so the app's data is published as one file encrypted with AES-256-GCM. The key
  comes from `APP_DATA_PASSWORD` through PBKDF2-SHA256 (250,000 iterations, random 16-byte salt); every
  export uses a fresh 12-byte IV. Without the password the file is unreadable, and a changed byte fails
  decryption.
- **Offline guessing is the main risk:** anyone can download the file and try passwords. Use a long random
  password (the default is 24 random characters, about 144 bits) and never a reused one.
- The file holds only what the app shows: picks, suggestions, prices and the cited passages. No run errors,
  raw documents, logs or keys.
- The password never leaves the device. The app keeps only the derived key, which stops working when the
  password changes (a new salt). To cut someone off, change the password and push: everyone else needs
  the new one.
- Old encrypted copies stay in the git history and on devices that downloaded them; a new password protects
  only data published from then on.

**Agent.**
- The model has one write tool, `save_suggestion`. The code fills in `ticker` and `as_of`, so the model
  can't change them.
- Citations must have come back from a search in the same conversation.
- Every number must match a value a tool returned.
- Steps and tool calls are capped.
- These rules also limit **prompt injection** from news or filing text: a malicious passage can at worst
  change wording that must still be cited and numerically grounded. It can't reach other tools, other
  tickers or the database.

**Website (Django).**
- Invite-only (`manage.py invite`); there is no public sign-up.
- Every page needs a login, and data is read on the server.
- The Content-Security-Policy allows only scripts from this site, the pinned and SRI-checked Chart.js on
  cdnjs, and inline scripts carrying a fresh nonce per request.
- Text from the LLM is auto-escaped, and source links must be `http(s)`.
- Login is throttled: 5 failures per username, or 20 per IP, within 15 minutes returns HTTP 429. The
  admin login goes through the same form.
- Sessions last 12 hours.
- In production: secure cookies, HSTS and HTTPS redirect.

**Local API (FastAPI).** It reads the whole database, so it answers requests from this machine only.
Setting `QUANT_API_TOKEN` allows remote access, but only with `Authorization: Bearer <token>`, compared
in constant time.

**CI (GitHub Actions).**
- The job's token is read-only (`permissions: contents: read`).
- Manual inputs are passed through environment variables, never pasted into the script, and checked
  against a strict pattern before use.

**Ollama.** Listens on `127.0.0.1:11434` by default. Don't set `OLLAMA_HOST=0.0.0.0` on a network you
don't control.

## Review findings (2026-11-11)

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | No limit on website login attempts: passwords could be guessed endlessly. The admin login had its own unthrottled form | Medium | **Fixed**: throttled login, admin login redirected to it |
| 2 | No Content-Security-Policy: escaping was the only defence against injected script | Medium | **Fixed**: nonce-based CSP, plus Permissions-Policy and CORP headers |
| 3 | The local API used the service key with no access control. Harmless on localhost, but it would expose everything if started with `--host 0.0.0.0` | Medium | **Fixed**: local requests only, or a bearer token |
| 4 | A Telegram network error could log the bot token, because `requests` includes the URL (which contains the token) in its messages | Medium | **Fixed**: only the error type is logged |
| 5 | The workflow's `GITHUB_TOKEN` had default permissions, and the manual `tickers` input could pass options like `--days 9999` | Low | **Fixed**: read-only token, validated inputs |
| 6 | `setuptools` 78.1.0 in the virtualenv has known vulnerabilities (PYSEC-2025-49, PYSEC-2026-3447, GHSA-xmj3-9gf7-h52w) | Low (build tool, not used at run time) | **Fixed**: upgraded to 84.2.1. `pip-audit` reports nothing else; `torch` can't be audited |
| 7 | Supabase Auth allowed public sign-ups by default | High once the app is live | **Resolved**: Supabase removed; the app reads a password-encrypted file |
| 9 | `scripts/setup.ps1` set `OLLAMA_HOST=0.0.0.0:11434`, exposing the model API to the local network (this machine never ran with it) | Low | **Fixed**: now `127.0.0.1:11434` |
| 10 | A comment in `ingest.yml` contained an empty `${{ }}`, which GitHub evaluates even in comments; the workflow became invalid ("No jobs were run") | High (daily ingest stopped) | **Fixed**; `tests/test_workflows.py` now checks every workflow |
| 8 | Git history checked for leaked keys (Supabase JWTs and secret keys, Telegram tokens, API keys): none found. `.env` and `web/db.sqlite3` are not tracked | — | OK |

Tests for fixes 1–5 are in [tests/test_security.py](../tests/test_security.py).

## What you need to do

1. **Keep `APP_DATA_PASSWORD` long and random** (the default is). Share it only with people who may read
   the app, over a private channel.
2. **Change it if it leaks:** edit `.env`, run any job (or `python -m orchestration.export_app`) and push.
3. **Rotate a key** if it was ever pasted into a chat, an issue or a log, then update `.env`.
4. **The Django dashboard is a local tool.** Don't host it as it is.
5. Re-run `pip-audit` now and then. It's not a project dependency; install it in its own environment.

## Reporting a problem

This is a private project. Report security issues privately through the Contact links on the website
rather than in a public issue.
