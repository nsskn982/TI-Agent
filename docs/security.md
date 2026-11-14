# Security

*Review date: 2026-11-11.* What TI Agent protects, how, what the review found and fixed, and what you
still need to set up yourself.

## What we protect

| Asset | Why it matters | Where it lives |
|---|---|---|
| Local database (PostgreSQL) | Full read and write of all data | Docker on the laptop, listening on 127.0.0.1:5433 only. Password in `.env`; never in git or the app |
| API keys (Finnhub, FRED), Telegram bot token | Abuse of free quotas; posting as the bot | `.env` on the laptop |
| Suggestions | Publishing investment recommendations may fall under EU market rules (MAR) | Local database; shown only to invited, signed-in users |
| Website and app accounts | Access to the above | Django's SQLite (shared by the website and the app API) |

## How each part is protected

**Database (local PostgreSQL).**
- The container binds to `127.0.0.1` only, so other machines on the network can't connect. Only processes
  on the laptop (the pipeline, the dashboard, the app API) use it.
- `Store.rpc()` calls only the known search functions; everything else is plain SQL with bound parameters.

**App API (`/api/`, exposed through a Cloudflare Tunnel).**
- The tunnel's ingress rule forwards only `^/api/`; the dashboard and `/admin/` stay unreachable from the
  internet (404).
- Same invite-only accounts as the website. Login is throttled with the same counters as the web form
  (5 failures per username, 20 per IP, per 15 minutes → HTTP 429).
- Tokens are signed with `DJANGO_SECRET_KEY` (Django `signing`, salted) and expire after 12 hours.
  Disabling a user revokes access at once; rotating the secret key revokes every token.
- Read-only. Run summaries never include the `error` column, raw documents and chunks are never listed,
  and citations return only chunks some suggestion cites (at most 20 per call). Ticker and id inputs are
  validated; price windows are capped.
- No cookies, so no CSRF. CORS answers only `APP_ALLOWED_ORIGINS` (the GitHub Pages origin).
- `run_api.cmd` runs with `DJANGO_DEBUG=false` behind the tunnel (`DJANGO_BEHIND_PROXY=true`, HTTPS
  redirect, HSTS, secure cookies).

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
| 7 | Supabase Auth allowed public sign-ups by default | High once the app is live | **Resolved**: Supabase removed; the app uses the website's invite-only accounts |
| 9 | `scripts/setup.ps1` set `OLLAMA_HOST=0.0.0.0:11434`, exposing the model API to the local network (this machine never ran with it) | Low | **Fixed**: now `127.0.0.1:11434` |
| 10 | A comment in `ingest.yml` contained an empty `${{ }}`, which GitHub evaluates even in comments; the workflow became invalid ("No jobs were run") | High (daily ingest stopped) | **Fixed**; `tests/test_workflows.py` now checks every workflow |
| 8 | Git history checked for leaked keys (Supabase JWTs and secret keys, Telegram tokens, API keys): none found. `.env` and `web/db.sqlite3` are not tracked | — | OK |

Tests for fixes 1–5 are in [tests/test_security.py](../tests/test_security.py).

## What you need to do

1. **Set a real `DJANGO_SECRET_KEY`** before starting `run_api.cmd`. It signs the app tokens.
2. **Keep the tunnel limited to `/api/`** (the `path: ^/api/` rule in the README). Never point the tunnel at
   the dashboard's dev server (`runserver`, `DJANGO_DEBUG=true`).
3. **Invite only people you trust** (`python web/manage.py invite`). Deactivate an account in `/admin/`
   (locally) to revoke its app access immediately.
4. **Change the database password** from the default if other people use this laptop: set
   `POSTGRES_PASSWORD` before the first `docker compose up` and update `DATABASE_URL`.
5. **Rotate a key** if it was ever pasted into a chat, an issue or a log, then update `.env`.
6. Re-run `pip-audit` now and then. It's not a project dependency; install it in its own environment.

## Reporting a problem

This is a private project. Report security issues privately through the Contact links on the website
rather than in a public issue.
