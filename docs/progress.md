# Progress report: Phases 1 and 2

*Status as of 2026-11-11.* This report covers Phase 1 (Foundations) and Phase 2 (Knowledge) from the
[roadmap](../README.md#roadmap). For how the parts work, see [architecture.md](architecture.md).

## Summary

| Phase | Code | Tests | Committed | Gate | Gate status |
|---|---|---|---|---|---|
| P1 Foundations | Done | 20 pass | Yes, `7b7c4b0`, pushed | 7 days of data without errors | **Not started.** The daily workflow has 0 runs; the first one is scheduled for 22:30 UTC on 2026-11-11 |
| P2 Knowledge | Done | 22 pass | **No** (working tree only) | Relevant chunks on 10 test queries | **Blocked.** Needs P1 data in Supabase |

All of the code for both phases is written and tested offline (42 tests, no network or keys needed).
Neither phase has passed its gate yet, because both gates need a live Supabase project with data in it.

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

1. Commit and push the Phase 2 changes.
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

## Next: Phase 3 (Agent)

The M6 agent's read-only tools (`search_knowledge`, `get_features`, `get_prices`, `get_macro`) map
directly onto the Phase 2 API routes. That leaves the agent loop, the prompt and Modelfile,
`save_suggestion` with schema validation and a check that every cited chunk exists, the weekly
orchestration (M8), and Telegram delivery.
