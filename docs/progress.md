# Progress report

*Status as of 2026-11-11.* For how the parts work, see [architecture.md](architecture.md); for the
threat model and the security review, see [security.md](security.md).

## Summary

| Phase | What it covers | Code | Gate | Gate status |
|---|---|---|---|---|
| P1 Foundations | Ingestion, processing, storage (M1–M3) | Done | 7 days of data without errors | **Day 0–1.** 2-year backfill loaded with 0 errors; the first scheduled daily run is 22:30 UTC on 2026-11-11. Earliest pass: **2026-11-19** |
| P2 Knowledge | Quant engine, hybrid retrieval (M4–M5) | Done | Relevant chunks on 10 test queries | **Passed 2026-11-11.** 10/10 automatic checks; 10/10 on-topic by manual review with rerank |
| P3 Agent | Agent, weekly run, Telegram (M6, M8, M9) | Done | 4 weekly runs of valid, cited JSON | **1 / 4.** Run #2 was `ok` for all 5 tickers |
| Web | Django dashboard (M9 web) | Done | — | Running locally against live data |
| App | Flutter client | Code written, not yet built | — | Needs the Flutter SDK and `db/rls.sql` re-run (see below) |
| P5 Research | QAOA portfolio, M10 evaluation | Not started | — | — |

**Tests:** 95 Python tests, all passing offline (no network or keys needed).

**Git:** all work is on branch `phase-2-knowledge`, **not pushed**. The daily GitHub Action runs from
`main`, which still has Phase 1 code only, until the branch is merged.

## What exists today

| Area | Where | Notes |
|---|---|---|
| Database schema, RLS, grants | [db/schema.sql](../db/schema.sql), [db/rls.sql](../db/rls.sql) | Safe to re-run. Signed-in users read results only; raw data and writes need the service key |
| Ingestion: prices, news, filings, XBRL, macro | [ingestion/](../ingestion/) | Point-in-time: filings by EDGAR acceptance time, XBRL by `filed`, FRED with release lags |
| Processing: chunking, MiniLM embeddings, FinBERT | [processing/](../processing/) | 9,627 chunks, 1,240 scored news items |
| Quant features and local API | [quant/](../quant/) | API answers local requests only unless `QUANT_API_TOKEN` is set |
| Hybrid retrieval with rerank | [retrieval/](../retrieval/) | Dense + keyword, RRF, cross-encoder, ≤ 2 chunks per document |
| Agent (Qwen3.5 4B via Ollama) | [agent/](../agent/) | Citations and numbers checked in code; English-only theses; caps on steps and tool calls |
| Weekly run + Telegram | [orchestration/](../orchestration/), [delivery/](../delivery/) | Status `ok` / `partial` / `error`; Telegram not configured yet |
| Daily ingest job | [.github/workflows/ingest.yml](../.github/workflows/ingest.yml) | 22:30 UTC weekdays; read-only token; validated manual inputs |
| Website | [web/](../web/) | Scroll-story home page, ticker charts, citations, pipeline status, Contact tab |
| Flutter app | [app/](../app/) | Supabase Auth + anon key; see [app/README.md](../app/README.md) |

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

Gate query (Supabase SQL editor):

```sql
select r.id, r.as_of, r.status, count(s.id) as suggestions,
       count(*) filter (where cardinality(s.sources) > 0) as cited
from agent_runs r left join suggestions s on s.run_id = r.id
group by r.id order by r.as_of desc limit 8;
```

## Website

An invite-only Django site in [web/](../web/) that reads Supabase server-side (the service key never
reaches the browser).

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
detail with a price chart and history, cited passages. **Not yet compiled**: the Flutter SDK isn't
installed on this machine. Before first use:

1. Re-run [db/rls.sql](../db/rls.sql) in the Supabase SQL editor. It adds the app's read access: run
   summaries without error text, and `app_citations()` for cited passages only.
2. In Supabase, turn **off** public sign-ups and invite users (see [security.md](security.md)).
3. Install Flutter and follow [app/README.md](../app/README.md).

## Next steps

1. Push `phase-2-knowledge` and merge it into `main`, so the daily job runs the current code.
2. Watch the daily job through 2026-11-19 for the Phase 1 gate.
3. Three more weekly runs for the Phase 3 gate. Close heavy apps during the run (the model needs about
   4.6 GB of commit memory).
4. Set up the Telegram bot (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) and `scripts/register_weekly_task.ps1`.
5. Build and test the Flutter app.
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
