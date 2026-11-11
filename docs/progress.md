# Progress report: Phases 1–3

*Status as of 2026-11-11.* This report covers Phase 1 (Foundations) and Phase 2 (Knowledge) from the
[roadmap](../README.md#roadmap). For how the parts work, see [architecture.md](architecture.md).

## Summary

| Phase | Code | Tests | Committed | Gate | Gate status |
|---|---|---|---|---|---|
| P1 Foundations | Done | 20 pass | Yes, `7b7c4b0`, pushed | 7 days of data without errors | **Day 0.** Supabase set up and 2-year backfill loaded with 0 errors; the first scheduled daily run is 22:30 UTC on 2026-11-11 |
| P2 Knowledge | Done | 22 pass | Yes, `b153cf5` on branch `phase-2-knowledge` (not pushed) | Relevant chunks on 10 test queries | **Passed 2026-11-11:** 10/10 automatic checks; all 10 on-topic by manual review with rerank |
| P3 Agent | Done; works with the real model on real data (smoke test) | 27 pass | No | 4 weekly runs of valid, cited JSON | **Blocked.** Needs Ollama + P1/P2 data |

All of the code for the three phases is written and tested offline (69 tests, no network or keys needed).
Phase 2 has passed its gate. Phase 1 needs 7 clean daily runs (earliest 2026-11-19), and Phase 3 needs
4 weekly runs.

## Phase 1: Foundations (M1 ingestion, M2 processing, M3 storage)

### Done

| Item | Where | Notes |
|---|---|---|
| Supabase schema for all phases | [db/schema.sql](../db/schema.sql) | Includes the tables for Phases 3–5 (`suggestions`, `portfolio_runs`, `performance`, agent logs), so later phases don't need a migration |
| Row-level security | [db/rls.sql](../db/rls.sql) | Signed-in users can only read results. Raw data and all writes need the service key |
| Price ingestion (yfinance) | [ingestion/prices.py](../ingestion/prices.py) | Checked against live data |
| News ingestion (Finnhub) | [ingestion/finnhub.py](../ingestion/finnhub.py) | Rate-limited to the free tier (60 calls/min) |
| Filing ingestion (SEC EDGAR) | [ingestion/edgar.py](../ingestion/edgar.py) | 10-K, 10-Q, 8-K. Timestamped at the moment of public release (EDGAR acceptance time) |
| Macro ingestion (FRED) | [ingestion/fred.py](../ingestion/fred.py) | 8 series |
| Ingestion runner | [ingestion/run.py](../ingestion/run.py) | A failure in one source or ticker doesn't stop the rest. Every run is logged to `ingestion_runs` |
| Chunking + embedding | [processing/](../processing/) | Splits on sentence boundaries; MiniLM 384-dim vectors; safe to re-run |
| Daily GitHub Actions job | [.github/workflows/ingest.yml](../.github/workflows/ingest.yml) | 22:30 UTC on weekdays; can also be started by hand with custom days/tickers |
| Windows setup script | [scripts/setup.ps1](../scripts/setup.ps1) | Python venv + Ollama |

### Not done yet (blocks the gate)

1. **Supabase project.** No local `.env` exists, so the database hasn't been checked from this machine.
   Run `db/schema.sql` and then `db/rls.sql` in the Supabase SQL editor.
2. **Repository secrets.** `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY` and
   `SEC_USER_AGENT` must be set under *Settings → Secrets and variables → Actions*. We couldn't check
   them from here. If any are missing, the first scheduled run will fail.
3. **Backfill.** Run the workflow by hand once with `days = 730`, or run
   `python -m ingestion.run --days 730` locally.
4. **Seven clean runs.** The job only runs on weekdays. If the first run tonight succeeds, the earliest
   possible gate pass is the run on **2026-11-19**.

To check the gate, run this in the Supabase SQL editor:

```sql
select date(started_at) as day, job, status, counts, jsonb_array_length(errors) as n_errors
from ingestion_runs
order by started_at desc
limit 20;
```

The gate passes when 7 consecutive daily runs show `status = 'ok'` for both `ingestion` and `processing`.

## Backfill and Phase 2 gate (2026-11-11)

Supabase project set up: schema, RLS and grants applied, `public` added to the Data API's exposed
schemas. Every API key checked with a real request. The 2-year backfill (`python -m ingestion.run --days 730`,
then `python -m processing.run`) finished with **0 errors**:

| Data | Rows | | Data | Rows |
|---|---|---|---|---|
| Prices (5 tickers + SPY) | 3,306 | | Documents | 1,391 (1,240 news + 151 filings) |
| XBRL facts | 2,679 | | Chunks with embeddings | 9,627 |
| Macro observations | 2,604 | | News items scored by FinBERT | 1,240 |

`python -m retrieval.evaluate` against this data (as of 2026-11-11, k = 5):

| Mode | Automatic checks | On-topic top results (manual review) |
|---|---|---|
| Hybrid (vector + keyword) | 10/10 | about 7/10; weaker on AAPL China, NVDA export controls, GOOGL YouTube |
| Hybrid + cross-encoder rerank | 10/10 | 10/10; e.g. "Azure and other cloud services revenue grew 39%", "shifting and expanding export control restrictions" |

As a result, the agent's `search_knowledge` tool now reranks by default (about 0.5 s per query on CPU).
News chunks rarely appeared in the top results for these queries. They are short (headline plus summary)
and the queries are about filings, so this is expected; the agent searches news with `source: "news"`.

## Phase 2: Knowledge (M4 quant engine, M5 retrieval)

### Done

| Item | Where | Checked against live data |
|---|---|---|
| Technical indicators (returns, SMA, RSI, MACD, volatility, drawdown, beta, relative strength) | [quant/indicators.py](../quant/indicators.py) | Unit tests only |
| Point-in-time fundamentals from SEC XBRL | [ingestion/fundamentals.py](../ingestion/fundamentals.py), [quant/fundamentals.py](../quant/fundamentals.py) | **Yes.** AAPL TTM revenue $400.4B and EPS $6.42 as of 2025-06-01 match the reported figures; MSFT and AMZN also checked |
| FinBERT news sentiment | [processing/sentiment.py](../processing/sentiment.py), [quant/sentiment.py](../quant/sentiment.py) | **Yes.** Positive, negative and neutral test headlines were labelled correctly |
| Macro snapshot with release lags | [quant/macro.py](../quant/macro.py) | Unit tests only |
| Hybrid retrieval (vector + keyword, RRF, optional rerank) | [retrieval/search.py](../retrieval/search.py) | Reranker checked live. The SQL side has not been run on Supabase |
| FastAPI service (`/features`, `/prices`, `/macro`, `/search`) | [quant/api.py](../quant/api.py) | Tested with FastAPI's test client against an in-memory store |
| Gate evaluation script + 10 queries | [retrieval/evaluate.py](../retrieval/evaluate.py), [retrieval/eval_queries.json](../retrieval/eval_queries.json) | Not run yet (needs data) |
| Schema additions (`fundamentals`, sentiment columns, new search functions) | [db/schema.sql](../db/schema.sql) | Both SQL files parse with the Postgres parser (`pglast`), but haven't been run against a real database |

### Fixes to Phase 1 made during Phase 2

- **Vector search could return too few results.** pgvector's HNSW index applies `WHERE` filters
  after the approximate search. So a search filtered to one ticker could quietly return fewer than
  `k` chunks. Ticker-filtered queries now do an exact search instead.
- **Keyword search almost never matched.** It required every word of the question to appear in a
  chunk, and natural-language questions rarely do. It now matches any of the words, ranked by how
  closely they appear together.
- **Old prices drifted out of line.** Adjusted closes are recalculated by the data provider after
  every dividend or split, but old rows were never refreshed. Each run now re-writes about 2 years of
  prices so the whole series stays consistent.

### Not done yet

1. Push branch `phase-2-knowledge` and merge it into `main`.
2. Re-run `db/schema.sql` and `db/rls.sql`. Both are safe to run again on an existing database.
3. Backfill fundamentals (`python -m ingestion.run --sources fundamentals --days 730`), then run
   `python -m processing.run` to score existing news.
4. Run `python -m retrieval.evaluate` with and without `--rerank`, then read the snippets yourself.
   The gate is about whether results are *relevant*; the automatic checks only test for keyword matches.

## Known limitations

| Limitation | Impact | Possible fix |
|---|---|---|
| Finnhub's free tier gives about 1 year of company news, headline and summary only | No full article text; short history for backtests | Add GDELT or RSS feeds |
| Filings are cut off at 300k characters | The end of a very long 10-K can be lost | Extract specific sections (Item 1A, Item 7) |
| For 8-Ks, only the main document is fetched | The press release (usually exhibit 99.1) is missed | Read the filing index and fetch EX-99 exhibits |
| Some companies use XBRL tags not on our list (e.g. AMZN reports no gross profit) | Some ratios come back `null` | Add more fallback tags as they turn up |
| Quarterly EPS is derived by subtracting year-to-date figures | Slightly off when the share count changes during the year | Rebuild EPS from net income and diluted shares |
| FRED values have no release timestamp | The fixed release delays we use are conservative estimates | Use ALFRED's historical vintages |
| News-sentiment features only cover news ingested since Phase 1 | Sentiment history starts at the backfill window | None needed; it fills in over time |

## Phase 3: Agent (M6 agent, M8 weekly run, M9 Telegram)

*Code added 2026-11-11, on top of branch `phase-2-knowledge`, not yet committed.* The gate is
**4 weekly runs of valid, cited JSON**.

### Done

| Item | Where | Status |
|---|---|---|
| Suggestion schema + check that numbers come from tools | [agent/schema.py](../agent/schema.py) | Unit tests |
| Tools: 4 read-only + `save_suggestion`, all bound to the run's as-of date | [agent/tools.py](../agent/tools.py) | Unit tests |
| Ollama client with a fallback for tool calls written as text | [agent/llm.py](../agent/llm.py) | Tested against a fake HTTP session |
| Agent loop with step and tool-call caps and context-budget control | [agent/agent.py](../agent/agent.py) | Tested with a scripted fake LLM |
| System prompt + model build | [agent/prompts/system.md](../agent/prompts/system.md), [scripts/create_model.ps1](../scripts/create_model.ps1) | Smoke-tested with Qwen3.5 4B (see below) |
| Weekly run with retry and run status (`ok` / `partial` / `error`) | [orchestration/weekly_run.py](../orchestration/weekly_run.py) | Unit tests |
| Telegram digest and alerts | [delivery/telegram.py](../delivery/telegram.py) | Tested against a fake HTTP session |
| Task Scheduler registration | [scripts/register_weekly_task.ps1](../scripts/register_weekly_task.ps1) | Passes the PowerShell parser; not registered yet |

The tests cover these cases, among others:
- a made-up citation is rejected and the fixed version is accepted
- a made-up figure (e.g. "37.5%") is rejected
- the model can't override `ticker` or `as_of`
- unknown tools such as `place_trade` and tickers off the watchlist are rejected
- the step and tool-call caps stop the run
- context trimming never drops the system prompt
- a retry keeps a horizon that was already saved
- a crash is recorded as `error` and sends an alert

The full suite has 69 tests.

### Not done yet (blocks the gate)

1. Run more smoke tests (all 5 watchlist tickers, with news once `FINNHUB_API_KEY` is set) to see
   how often a ticker fails within the step cap.
2. Phases 1 and 2 must have data in Supabase first (see above). Then re-run `db/schema.sql`, which adds
   the `partial` run status.
3. Create a Telegram bot with BotFather, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, and run
   `scripts/register_weekly_task.ps1`.

### Smoke test with the real model (2026-11-11)

[scripts/smoke_agent.py](../scripts/smoke_agent.py) loads real data into the in-memory store and runs
the agent on Ollama: yfinance prices, SEC filings and XBRL facts embedded with MiniLM. News and macro
were not loaded (no Finnhub or FRED keys), so the agent had filings and computed features only.

| Ticker | Result | Model turns | Tool calls | Rejected saves | Time | Stances (medium / long) |
|---|---|---|---|---|---|---|
| AAPL | Both saved | 8 | 12 | 3 | 69 s | bullish 0.60 / bullish 0.58 |
| MSFT | Both saved | 4 | 10 | 0 | 37 s | neutral 0.60 / bullish 0.62 |

Model: `qwen3.5:4b` (Q4_K_M), text-only, 16K context, thinking on, 100% on the RTX 4050's GPU,
3.8–16.5 s per turn. What we learned:

- **The guardrails work on a real model.** For AAPL they caught one made-up citation (`chunk_2089`) and
  figures not found in any tool output; each time the model corrected itself and resubmitted.
- **Fixed: false rejections.** Figures like "$100 billion" that appear in filing text weren't counted as
  tool numbers. Tool outputs are now read with the same unit rules as the thesis.
- **Fixed: the vision encoder didn't fit.** Stock `qwen3.5:4b` includes a ~650 MB vision projector. It
  didn't fit beside the weights and a 16K KV cache on 6 GB, and Ollama's fallback crashed.
  `scripts/create_model.ps1` builds a text-only model that keeps tool calling and thinking.
- Theses quote computed values correctly (TTM growth, FCF, returns, distance from the moving
  averages) and cite filing passages for qualitative claims.

To check the gate in the Supabase SQL editor:

```sql
select r.id, r.as_of, r.status, count(s.id) as suggestions,
       count(*) filter (where cardinality(s.sources) > 0) as cited
from agent_runs r left join suggestions s on s.run_id = r.id
group by r.id order by r.as_of desc limit 8;
```

The gate passes after 4 weekly runs with `status = 'ok'` and two cited suggestions per ticker.
Since the first real run can't happen before data has accumulated, the earliest realistic pass is
four Saturdays after the first successful run.
