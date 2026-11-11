# Security

*Review date: 2026-11-11.* What TI Agent protects, how, what the review found and fixed, and what you
still need to set up yourself.

## What we protect

| Asset | Why it matters | Where it lives |
|---|---|---|
| Supabase service key | Bypasses row-level security: full read and write | `.env` on the laptop, GitHub encrypted secrets. Never in git, the browser or the app |
| API keys (Finnhub, FRED), Telegram bot token | Abuse of free quotas; posting as the bot | `.env`, GitHub secrets |
| Suggestions | Publishing investment recommendations may fall under EU market rules (MAR) | Supabase; shown only to invited, signed-in users |
| Website and app accounts | Access to the above | Django's SQLite (website), Supabase Auth (app) |

## How each part is protected

**Database (Supabase).**
- Row-level security is on for every table.
- Signed-in users can read only `tickers`, `prices`, `suggestions`, `portfolio_runs`, `performance`, and
  six columns of `agent_runs` (not `error`).
- Raw documents and chunks stay closed. The app gets cited passages through `app_citations()`, which
  returns only chunks that some suggestion cites, at most 20 per call.
- Only the service role can write. Retrieval functions can't be called with the public (anon) key.

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

**Local API (FastAPI).** It reads with the service key, so it answers requests from this machine only.
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
| 7 | Supabase Auth allows public sign-ups by default. Once the app ships, anyone could create an account and read results | High once the app is live | **Action needed** (below) |
| 8 | Git history checked for leaked keys (Supabase JWTs and secret keys, Telegram tokens, API keys): none found. `.env` and `web/db.sqlite3` are not tracked | — | OK |

Tests for fixes 1–5 are in [tests/test_security.py](../tests/test_security.py).

## What you need to do

1. **Turn off public sign-ups** in Supabase: *Authentication → Sign In / Providers → Allow new users to
   sign up*. Then add people with *Authentication → Users → Invite user*. Do this before giving anyone
   the app.
2. **Re-run [db/rls.sql](../db/rls.sql)** in the SQL editor. It is safe to run again, and it adds the
   app's limited read access.
3. **When deploying the website:**
   - set `DJANGO_DEBUG=false`, a long random `DJANGO_SECRET_KEY` and the real `DJANGO_ALLOWED_HOSTS`
   - add `DJANGO_BEHIND_PROXY=true` if TLS ends at a proxy
   - serve over HTTPS
   - the login throttle uses Django's cache; with several server processes, switch `CACHES` to a shared
     cache (Redis or the database), otherwise each process counts separately
4. **Rotate a key** if it was ever pasted into a chat, an issue or a log. Supabase: *Project Settings →
   API keys*. Then update `.env` and the GitHub secret.
5. Re-run `pip-audit` now and then. It's not a project dependency; install it in its own environment.

## Reporting a problem

This is a private project. Report security issues privately through the Contact links on the website
rather than in a public issue.
