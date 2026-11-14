# Progress report

*Status as of 2026-11-11.* For how the parts work, see [architecture.md](architecture.md); for the
threat model and the security review, see [security.md](security.md).

## 2026-11-14: moved from Supabase to a local PostgreSQL

- **Database:** Supabase is gone. Everything runs against PostgreSQL 17 + pgvector in Docker
  (`127.0.0.1:5433`), through the same [common/store.py](../common/store.py) interface (now psycopg 3).
  `db/rls.sql` was Supabase-specific and has been removed. **The data in Supabase was not migrated**: run
  the first load again (README → Setup, step 4). That resets the Phase 1 gate count.
- **Schedules:** the GitHub Actions daily ingest and Friday screen can't reach a local database. They're
  replaced by Windows scheduled tasks ([scripts/register_tasks.ps1](../scripts/register_tasks.ps1)): daily
  refresh, weekly screen, weekly AI run.
- **Refresh and retention:** after the first backfill only new data is downloaded
  ([ingestion/refresh.py](../ingestion/refresh.py)); the weekly screen then deletes data no module reads any
  more ([orchestration/retention.py](../orchestration/retention.py)).
- **App:** still on GitHub Pages. It now reads an invite-only JSON API on the laptop
  ([web/dashboard/api.py](../web/dashboard/api.py), `run_api.cmd`), reached through a Cloudflare Tunnel.
  The sections below that mention Supabase, `db/rls.sql` or the cloud workflows describe the old setup.

## Summary

| Phase | What it covers | Code | Gate | Gate status |
|---|---|---|---|---|
| P1 Foundations | Ingestion, processing, storage (M1–M3) | Done | 7 days of data without errors | **Day 0–1.** 2-year backfill loaded with 0 errors; the first scheduled daily run is 22:30 UTC on 2026-11-11. Earliest pass: **2026-11-19** |
| P2 Knowledge | Quant engine, hybrid retrieval (M4–M5) | Done | Relevant chunks on 10 test queries | **Passed 2026-11-11.** 10/10 automatic checks; 10/10 on-topic by manual review with rerank |
| P3 Agent | Agent, weekly run, Telegram (M6, M8, M9) | Done | 4 weekly runs of valid, cited JSON | **1 / 4.** Run #2 was `ok` for all 5 tickers |
| Web | Django dashboard (M9 web) | Done | — | Running locally against live data |
| App | Flutter client | Analyzed and tested locally (19 tests) | — | Needs the Cloudflare Tunnel and the `API_URL` variable (see README) |
| P5 Research | QAOA portfolio, M10 evaluation | Not started | — | — |

**Tests:** 95 Python tests, all passing offline (no network or keys needed).

**Git:** all work is on branch `phase-2-knowledge`, **not pushed**. The daily GitHub Action runs from
`main`, which still has Phase 1 code only, until the branch is merged.

## What exists today

| Area | Where | Notes |
|---|---|---|
| Database schema | [db/schema.sql](../db/schema.sql), [docker-compose.yml](../docker-compose.yml) | Local PostgreSQL 17 + pgvector; `python -m common.db_init` is safe to re-run |
| Ingestion: prices, news, filings, XBRL, macro | [ingestion/](../ingestion/) | Point-in-time: filings by EDGAR acceptance time, XBRL by `filed`, FRED with release lags |
| Processing: chunking, MiniLM embeddings, FinBERT | [processing/](../processing/) | 9,627 chunks, 1,240 scored news items |
| Quant features and local API | [quant/](../quant/) | API answers local requests only unless `QUANT_API_TOKEN` is set |
| Hybrid retrieval with rerank | [retrieval/](../retrieval/) | Dense + keyword, RRF, cross-encoder, ≤ 2 chunks per document |
| Agent (Qwen3.5 4B via Ollama) | [agent/](../agent/) | Citations and numbers checked in code; English-only theses; caps on steps and tool calls |
| Weekly run + Telegram | [orchestration/](../orchestration/), [delivery/](../delivery/) | Status `ok` / `partial` / `error`; Telegram not configured yet |
| Daily refresh | [run_daily.cmd](../run_daily.cmd), [scripts/register_tasks.ps1](../scripts/register_tasks.ps1) | Weekdays 23:45 local; new data only after the first run |
| Website | [web/](../web/) | Scroll-story home page, ticker charts, citations, pipeline status, Contact tab |
| Flutter app | [app/](../app/) | Reads the laptop's `/api/` through a Cloudflare Tunnel; see [app/README.md](../app/README.md) |

## Data loaded (backfill, 2026-11-11)

| Data | Rows | | Data | Rows |
|---|---|---|---|---|
| Prices (5 tickers + SPY) | 3,306 | | Documents | 1,391 (1,240 news + 151 filings) |
| XBRL facts | 2,679 | | Chunks with embeddings | 9,627 |
| Macro observations | 2,604 | | News items scored by FinBERT | 1,240 |

## Phase 2 gate: retrieval quality

`python -m retrieval.evaluate` (as of 2026-11-11, k = 5):

| Mode | Automatic checks | On-topic top results (manual review) |
|---|---|---|
| Hybrid (vector + keyword) | 10/10 | about 7/10; weaker on AAPL China, NVDA export controls, GOOGL YouTube |
| Hybrid + cross-encoder rerank | 10/10 | 10/10 |

The agent's `search_knowledge` therefore reranks by default (about 0.5 s per query on CPU).

## Phase 3: weekly runs

| Run | Result | Why |
|---|---|---|
| #1 | `error`, no suggestions | Windows ran out of commit memory (27.0 of 27.3 GB), so Ollama couldn't load the model. Failed cleanly, saved nothing invalid. |
| #2 | **`ok`: 5/5 tickers, 10 suggestions, 4 min** | The run now loads the model first, keeps it loaded, and retries memory-related load failures. |

Run #2 stances (1–3m / 6–24m): AAPL bullish / neutral, AMZN neutral / neutral, GOOGL neutral / bullish,
MSFT bullish / bullish, NVDA neutral / bullish; confidence 0.58–0.62. Four saves were rejected (figures not
found in any tool output) and corrected by the model.

**Quality issues found by reading the theses:**

| Issue | Status |
|---|---|
| Number check accepted "50%" because `sma_50` is a field *name* | **Fixed**: only JSON values count, dates ignored |
| Risk written partly in Chinese ("AI adoption不及预期") | **Fixed**: non-English text is rejected so the model rewrites it. The line already saved stays until the next run |
| Real numbers under the wrong label (NVDA "$127B FCF yield" is FCF) | **Open.** Prompt glossary added; to be measured by M10 citation faithfulness |

Gate query (`docker exec -it ti-agent-db psql -U ti_agent`):

```sql
select r.id, r.as_of, r.status, count(s.id) as suggestions,
       count(*) filter (where cardinality(s.sources) > 0) as cited
from agent_runs r left join suggestions s on s.run_id = r.id
group by r.id order by r.as_of desc limit 8;
```

## Website

An invite-only Django site in [web/](../web/) that reads the local database server-side.

| Page | Shows |
|---|---|
| `/` | Scroll story: intro with this week's numbers, an at-a-glance grid, one pinned scene per ticker where both views slide in as you scroll (marked **New** / **Changed from …**), and a contact section |
| `/t/<ticker>/` | 12-month chart against SPY (indexed to 100), computed features, history |
| `/c/<id>/` | The exact cited passage, with a link to the source |
| `/status/` | Gate counters, agent runs, ingestion runs |

Checked in Edge with live data in light and dark mode, at desktop and phone widths, with no
Content-Security-Policy violations.

## Flutter app

Code in [app/](../app/): sign in with Supabase Auth, this week's suggestions as a scroll story, ticker
detail with a price chart and history, cited passages. One codebase for **web, Android and iOS**. It
replaces hosting the Django site: the app needs no server of its own.

- **Web:** [.github/workflows/app.yml](../.github/workflows/app.yml) runs `flutter analyze` and
  `flutter test`, builds the web version, and publishes it to GitHub Pages
  (`https://nsskn982.github.io/TI-Agent/`) on every push to `main`.
- **Android:** build an APK locally and send it to testers.
- **iOS:** needs a Mac and TestFlight.

**Not yet compiled.** Flutter isn't installed on this machine, so the first workflow run is the first
compile.

Before the first publish:

1. Re-run [db/rls.sql](../db/rls.sql) in the Supabase SQL editor. It adds the app's read access: run
   summaries without error text, and `app_citations()` for cited passages only.
2. In Supabase, turn **off** public sign-ups and create users (see [security.md](security.md)).
3. Add the `SUPABASE_ANON_KEY` repository secret, and set *Settings → Pages → Source* to *GitHub Actions*.

## Stock screen (added 2026-11-11, widened 2026-11-12)

The watchlist is no longer hand-picked. Every Friday a GitHub Action screens the **S&P 500 + S&P MidCap
400** (about 900 large- and mid-cap stocks) and keeps the **top 20**; see
[architecture.md §5a](architecture.md#5a-weekly-stock-screen-quantscreenpy-orchestrationscreen_runpy).

**2026-11-12 status:** the screen has **not run yet**. The `screens` table is empty, so last night's weekly
run (#3) fell back to the 5 stocks in `watchlist.txt`. It must be started once by hand (below).

**Deeper analysis (2026-11-12).** Each AI view now has a thesis, **bull case**, **bear case**, **catalysts**
and a **valuation** view, as well as risks. All of it is cited, and every number in it is checked against the
tool outputs. The app adds:
- a **Compare** table of all picks, sortable by any column
- daily figures per pick: last close and day move, position vs the 50- and 200-day averages, distance from
  the 52-week high, P/E

- **Score:** momentum among quality companies. Quality means profitable and cash-generating, from SEC
  financials. Momentum blends the 12-1 month return with 6- and 3-month returns vs the S&P 500, minus a
  volatility penalty.
- **Pipeline:** the picks get two years of news and filings, then embeddings. The daily ingest and the
  weekly agent run use the picks automatically.
- **App:** lists the picks in rank order, with each one's rank, sector and the numbers behind its place.
- **Checked live:** the Wikipedia list (503 constituents, 11 sectors, every one with an SEC CIK) and the
  batched price download (including `BRK-B` and `BF-B`).
- **Tests:** 14 new Python tests for parsing, the momentum maths, the quality filter, ranking,
  no-lookahead and the fallback; Dart tests for rank ordering.

**Before the first screen:** re-run `db/schema.sql` (adds `screens`, the ticker index columns and the
write-up columns), then `db/rls.sql` (lets the app read `screens`). Then start the
*Weekly stock screen (S&P 500 + MidCap 400)* workflow by hand.

**Costs:**
- **Weekly agent run:** goes from 5 tickers (~4 min) to 20 with the longer write-up (~30 min).
- **First screen:** downloads about 4–5 GB of SEC data for ~900 companies and backfills 20 tickers
  (~1.5–2 h in Actions; time limit 4 h).
- **Later weeks:** only new entrants are backfilled.
- **Database:** prices and fundamentals for 900 stocks add roughly 150 MB, which stays under the free
  0.5 GB.

## Next steps

1. Fix whatever the first *App (Flutter)* workflow run reports, then check the published web app.
2. Watch the daily job through 2026-11-19 for the Phase 1 gate.
3. Three more weekly runs for the Phase 3 gate. Close heavy apps during the run (the model needs about
   4.6 GB of commit memory).
4. Set up the Telegram bot (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) and `scripts/register_tasks.ps1`.
5. Android APK for testers; computed features in a table the app can read; push notifications.
6. Phase 5: QAOA portfolio experiment and the M10 evaluation (hit rate, calibration, citation faithfulness).

## Known limitations

| Limitation | Impact | Possible fix |
|---|---|---|
| Finnhub free tier: about 1 year of news, headline and summary only | No full article text; short history | Add GDELT or RSS feeds |
| Filings cut off at 300k characters | The end of a very long 10-K can be lost | Extract Item 1A / Item 7 |
| 8-Ks: main document only | Press release (EX-99.1) missed | Fetch EX-99 exhibits |
| Some XBRL tags not on our list | Some ratios `null` | Add fallback tags as they turn up |
| Quarterly EPS derived from year-to-date figures | Slightly off when share count changes | Rebuild from net income and diluted shares |
| FRED values have no release timestamp | Release delays are conservative estimates | Use ALFRED vintages |
| A 4B model sometimes mislabels numbers | Thesis wording can be wrong even when the number is real | M10 faithfulness evaluation; larger model when hardware allows |
