# Architecture: Phases 1 and 2

This document describes how TI Agent's data and knowledge layers work (modules M1–M5) and why they
are built this way. Numbers in square brackets, such as [[3]](references.md#ref-3), point to the
[references](references.md).

TI Agent is a retrieval-augmented generation (RAG) system [[1]](references.md#ref-1), [[2]](references.md#ref-2).
A local LLM writes trading suggestions, but only from evidence it retrieves and numbers it gets from
code. Phases 1 and 2 build that evidence base.

```
            daily, GitHub Actions                                 laptop, on demand
 ┌──────────────────────────────────────────────┐        ┌───────────────────────────────┐
 │ M1 ingestion            M2 processing         │        │ M4 quant engine   M5 retrieval │
 │ yfinance  ─┐                                  │        │  /features        /search      │
 │ Finnhub   ─┼─► documents ─► chunks+embeddings │        │  /prices                       │
 │ EDGAR     ─┤        └─► FinBERT sentiment     │        │  /macro                        │
 │ XBRL      ─┤  fundamentals                    │        └──────────────▲────────────────┘
 │ FRED      ─┘  prices, macro_series            │                       │ reads (service key)
 └───────────────────────┬──────────────────────┘                       │
                         ▼ writes (service key)                          │
                ┌─────────────────────────────────────────────────────────┴┐
                │ M3 Supabase: Postgres + pgvector (HNSW) + full-text search  │
                └────────────────────────────────────────────────────────────┘
```

Supabase is the only connection between modules: each module reads from and writes to it, and none
calls another directly. All database access goes through [common/store.py](../common/store.py).
Tests replace it with an in-memory fake ([tests/fakes.py](../tests/fakes.py)).

## 1. No-lookahead rule

The biggest risk in backtesting an LLM on financial data is lookahead: the model sees information that
was not public yet on the date it is supposedly reasoning about. Glasserman and Lin show that GPT-based
sentiment on news already contains lookahead bias through what the model memorised in training
[[3]](references.md#ref-3). We can't remove what the LLM memorised. We can make sure that
**everything the system feeds it was public before the `as_of` date**:

| Data | Timestamp used | Rule |
|---|---|---|
| Prices | Trading date | `date < as_of` |
| News | Finnhub publish time | `published_at < as_of` |
| Filings and their chunks | EDGAR **acceptance** time (when it went public), else end of the filing day | `published_at < as_of` |
| XBRL fundamentals | Filing date of each fact | `filed < as_of`. For each period, the latest filing known at `as_of` wins |
| Macro (FRED) | Observation date **plus a release delay** (1 day for daily series, 35–45 days for monthly) | `date + lag ≤ as_of` |

This rule is enforced in the SQL search functions (`match_chunks` and `keyword_chunks`), checked a second
time in Python ([retrieval/search.py](../retrieval/search.py)), and tested
([tests/test_retrieval_api.py](../tests/test_retrieval_api.py) plants a document dated after `as_of`
and asserts it is never returned).

## 2. M1: Ingestion ([ingestion/](../ingestion/))

| Source | Module | What is stored | Free-tier notes |
|---|---|---|---|
| yfinance | `prices.py` | Daily OHLCV and adjusted close for the watchlist plus `BENCHMARK` (SPY) | About 2 years re-fetched every run, so adjusted prices stay consistent |
| Finnhub | `finnhub.py` | Headline and summary as a `documents` row (`source='news'`) | 60 calls/min; about 1 year of history |
| SEC EDGAR | `edgar.py` | Main document of 10-K, 10-Q and 8-K filings, converted to plain text | Max 10 requests/s; User-Agent must include a contact email |
| SEC XBRL | `fundamentals.py` | Each financial fact as reported in each filing (`fundamentals` table) | Same rules as EDGAR |
| FRED | `fred.py` | 8 macro series | Free API key |

[ingestion/run.py](../ingestion/run.py) runs each source for each ticker separately. One failure is
logged and the rest carry on. Each run writes one row to `ingestion_runs`, which the Phase 1 gate uses.
Documents are unique on `(ticker, source, source_id)` and inserted with `ignore_duplicates`, so re-running
a window never resets processing that's already done.

## 3. M2: Processing ([processing/](../processing/))

**Chunking** ([chunk.py](../processing/chunk.py)). Text is split at sentence boundaries into chunks of
at most 180 words, with 30 words of overlap between neighbours. MiniLM [[5]](references.md#ref-5),
as packaged by sentence-transformers [[4]](references.md#ref-4), reads at most 256 word-pieces, and 180
English words stays under that limit. News items stay as one chunk (headline + summary).

**Embedding** ([embed.py](../processing/embed.py)). `all-MiniLM-L6-v2` produces normalised
384-dimensional vectors. It is small enough to run on the free GitHub Actions CPU runners. Each chunk is
embedded with a short header, `"AAPL 10-K: …"`, so passages from different companies end up apart in
vector space. The stored text has no header; queries filtered by ticker get the same prefix.

**Sentiment** ([sentiment.py](../processing/sentiment.py)). Each news item is scored with FinBERT
[[6]](references.md#ref-6). The score is `P(positive) − P(negative)`, from −1 to 1. Results are written
in batches through the `set_sentiment` database function. FinBERT is trained on financial text and
handles finance-specific language that general sentiment models get wrong (e.g. "beats estimates").
Domain models such as BloombergGPT [[7]](references.md#ref-7) and FinGPT [[8]](references.md#ref-8)
point the same way; FinBERT is the version of that idea that runs on a free CPU.

Processing can safely run again: a document's chunks are replaced as a whole, and a document that fails
is marked with `process_error` so it isn't retried forever.

## 4. M3: Storage ([db/](../db/))

- `chunks.embedding` uses an **HNSW** index [[9]](references.md#ref-9) for cosine similarity, plus a
  stored `tsvector` column with a GIN index for keyword search.
- **Filtered vector search.** HNSW finds candidates first and applies `WHERE` filters afterwards. A
  selective filter (one ticker out of many) can therefore return fewer than `k` rows without any error.
  `match_chunks` handles this by doing an exact search when a ticker is given; one ticker's corpus is
  small, so this is fast. Unfiltered queries use the index with a wider `ef_search`.
- **Row-level security.** Signed-in (invite-only) users can read `suggestions`, `portfolio_runs`,
  `performance`, `prices` and `tickers`. Everything else, including all search functions, needs the
  service key.

## 5. M4: Quant engine ([quant/](../quant/))

The README's guardrail is that *numbers come from code, never from the LLM*. Every number the agent
sees comes from these pure functions.

**Technicals** ([indicators.py](../quant/indicators.py)), computed on adjusted closes:
- trailing returns over 1, 3, 6 and 12 months (21, 63, 126 and 252 trading days)
- 50- and 200-day moving averages, and how far the price is above or below each
- RSI(14) with Wilder smoothing, and MACD(12, 26, 9)
- 20- and 60-day annualised volatility
- 1-year maximum drawdown and distance from the 52-week high and low
- 1-year beta and 3-month relative strength against the benchmark

**Point-in-time fundamentals** ([fundamentals.py](../quant/fundamentals.py)):
1. Keep facts filed before `as_of`. For each `(start, end)` period, take the latest filing. When a
   metric has several possible XBRL tags (companies change tags over time), use the first tag in
   priority order.
2. Work out quarterly figures from year-to-date totals that share a start date (Q2 = H1 − Q1,
   Q4 = FY − 9M). Cash-flow statements are usually reported this way only.
3. TTM is the sum of the last 4 quarters, rejected if the quarters have gaps. Year-on-year growth
   compares this with the TTM figure from about a year earlier.
4. Ratios: gross, operating and net margin; P/E (only when EPS is positive); FCF and FCF yield;
   debt-to-equity; market cap = last close × shares outstanding from the cover page.

Checked against reported figures for AAPL (TTM revenue $400.4B and EPS $6.42 as of 2025-06-01), MSFT
and AMZN; see [progress.md](progress.md).

**Sentiment aggregates** ([sentiment.py](../quant/sentiment.py)): number of articles and mean score
over 7, 30 and 90 days; the 7-day minus 30-day trend; the share of positive headlines; and a z-score
for news volume this week against the previous 12 weeks.

**Macro** ([macro.py](../quant/macro.py)): latest value of each series after its release delay, the
1- and 3-month changes, and CPI year-on-year.

**API** ([api.py](../quant/api.py)), run with `uvicorn quant.api:app`. Dates in the future are rejected
with HTTP 400, and an unknown ticker returns 404. All floats are rounded, and NaN/inf come back as `null`.

## 5a. Weekly stock screen ([quant/screen.py](../quant/screen.py), [orchestration/screen_run.py](../orchestration/screen_run.py))

The universe is the **S&P 500** (large caps) plus the **S&P MidCap 400**, about 900 stocks. Small caps
(S&P 600) are left out to keep the weekly SEC download and database size inside the free tiers.

Analysing all of them with retrieval and the LLM doesn't fit the free tier: well over a million text chunks
(Supabase free is 0.5 GB), and more than 10 hours of laptop GPU time per week. So the pipeline is a
two-stage filter:

1. **Screen everything, cheaply** (GitHub Actions, Fridays 23:30 UTC, [screen.yml](../.github/workflows/screen.yml)):
   - Constituents come from Wikipedia's S&P 500 and S&P 400 lists, stored in Yahoo/SEC form (`BRK-B`).
     Each stock is tagged with its index (`in_sp500` / `in_sp400`); the S&P 400 list has no CIK, so CIKs
     come from SEC's ticker map.
   - Each pick's stored metrics also include the levels shown in the app's daily view: 52-week high and
     low, 50- and 200-day averages, 1-month return, P/E and debt to equity.
   - About 800 days of prices are downloaded in batches of 100.
   - SEC XBRL fundamentals are fetched for every company.
   - The score is computed in code from data strictly before the as-of date.
2. **Analyse only the top N** (default 20). Picks with no documents get two years of news and filings, then
   chunking, embeddings and FinBERT. The daily ingest and the Saturday agent run default to the latest picks.
   `watchlist.txt` is used only before the first screen, or when `--tickers` is passed.

**Score: momentum among quality companies.**
- **Quality filter**, point in time from SEC facts:
  - the latest quarter ended less than 200 days ago
  - TTM net margin > 0
  - TTM free cash flow > 0 where it can be computed (banks often have no capex tag; for them FCF is
    unknown and doesn't fail the filter)
- **Score** among the companies that pass:
  - 0.50 × z(12-1 month return), the classic momentum signal [[R3]](references.md#ref-r3)
  - \+ 0.25 × z(6-month return vs SPY)
  - \+ 0.25 × z(3-month return vs SPY)
  - − 0.20 × z(6-month volatility)
  - z-scores are winsorised at ±3

The profitability and cash-flow filter follows the quality literature [[R4]](references.md#ref-r4). Each pick's
numbers are stored in `screens.metrics`, and the app shows them as "why it made the list". They come from code,
not the LLM.

**Limitations.**
- **Restructured companies:** a company that has just moved to a new SEC registrant (e.g. ExxonMobil
  Holdings Corp in 2026) has no four-quarter history under its new CIK. It shows as "no SEC financials" and
  is skipped until it has been filing under the new CIK for about a year.
- **Survivorship bias:** the universe is *today's* S&P 500, so backtests miss companies that left the index.
- **Hindsight:** past momentum doesn't guarantee future returns. The agent's stance is still judged relative
  to the S&P 500.

## 6. M5: Retrieval ([retrieval/](../retrieval/))

`Retriever.search(query, as_of, k, ticker, source, rerank, max_per_doc, recency_half_life_days)`:

1. **Dense search.** `match_chunks` returns the `5k` (at least 30) closest chunks by MiniLM
   embedding, a dense bi-encoder approach as in DPR [[10]](references.md#ref-10).
2. **Keyword search.** `keyword_chunks` uses Postgres full-text search: the query's words are combined
   with OR and ranked with `ts_rank_cd`. Keyword search matters here because exact terms carry a lot
   of meaning in finance: tickers, product names, "Item 1A", "Blackwell". The BEIR benchmark
   [[11]](references.md#ref-11) found that BM25-style keyword retrieval is a strong baseline that dense
   models often fail to beat on text unlike their training data.
3. **Fusion.** Reciprocal Rank Fusion [[R1]](references.md#ref-r1) with `k = 60` scores each chunk
   by `Σ 1/(60 + rank)` across the two lists. It needs no tuning and ignores the different score
   scales of the two searches.
4. **Optional recency decay.** The score is multiplied by `0.5^(age / half_life)`.
5. **Optional reranking.** A cross-encoder (`ms-marco-MiniLM-L-6-v2`) re-scores the top `4k` results.
   Rerankers like this were introduced by Nogueira and Cho [[12]](references.md#ref-12) and trained on
   MS MARCO [[13]](references.md#ref-13).
6. **Diversity.** At most `max_per_doc` (default 2) chunks from one document, so one long 10-K can't
   take every slot. Fewer, more varied passages also suit how LLMs read: Liu et al.
   [[14]](references.md#ref-14) found that models make less use of information buried in the middle
   of a long context.
7. Every result carries a `chunk_<id>` citation, which the Phase 3 agent must quote in `sources`.
   Checking those citations draws on work on making LLMs cite their sources [[15]](references.md#ref-15).

**Phase 2 gate** ([evaluate.py](../retrieval/evaluate.py)): for each of 10 queries, it checks that
`k` results come back, that they are all for the requested ticker (and source, if one was given),
that none are dated on or after `as_of`, and that an expected keyword appears in the top 3. It then
prints snippets so a person can judge relevance.

## 7. M6 agent, M8 weekly run, M9 Telegram (Phase 3)

**Agent loop** ([agent/agent.py](../agent/agent.py)). For each ticker, the model works in a loop:
it reasons, calls a tool, reads the result, and repeats until it has saved both suggestions
(ReAct [[16]](references.md#ref-16); tool use as in Toolformer [[17]](references.md#ref-17)). The model
is Qwen3.5 4B, running in Ollama as a text-only build ([scripts/create_model.ps1](../scripts/create_model.ps1)
leaves out the vision projector, which doesn't fit on 6 GB) with a 16K-token context, Qwen's
recommended sampling settings, and **thinking** turned on: the model
reasons before each reply. That reasoning is kept out of the conversation history, so it costs time
but no context. If a model can't think, the client switches thinking off automatically. Qwen3.5 has
no technical report on arXiv; its predecessor's report [[18]](references.md#ref-18) describes the
combined thinking and non-thinking design.

| Tool | Kind | Notes |
|---|---|---|
| `search_knowledge` | read | Phase 2 retriever, at most 6 passages of 600 characters each; every returned id is recorded |
| `get_features` | read | `/features` output with `null` values removed |
| `get_prices` | read | Weekly closes, at most 52 weeks |
| `get_macro` | read | `/macro` output |
| `save_suggestion` | **write** (the only one) | Checked and stored; the model gets an error message back if it breaks a rule |

**Guardrails are enforced in code** ([agent/tools.py](../agent/tools.py), [agent/schema.py](../agent/schema.py)),
because a 4B model doesn't reliably follow prompt rules:

- **Date and ticker are fixed by code.** No tool accepts an `as_of` parameter. `ticker` and `as_of` on a
  suggestion are always filled in by code, so values the model sends for them are ignored. Tickers
  outside the watchlist are rejected.
- **Citations must have been seen.** Every `sources` id must have been returned by `search_knowledge`
  in the same conversation. This catches made-up ids, and it applies the citation checking described
  by Gao et al. [[15]](references.md#ref-15) at the moment of saving.
- **Numbers must come from tools.** Every figure that looks like a claim (a decimal, a %, a $ amount,
  or a B/M/T/x suffix) in the thesis or risks must match, after rounding, a number some tool returned
  in that conversation. A ratio like `0.151` may be written `15.1%`. Plain integers (years, "S&P 500",
  "3 segments") are not checked.
- **Caps.** At most 12 model turns and 16 tool calls per ticker, and every call is logged to `tool_calls`.
- **Context budget.** When the context window overflows, Ollama silently drops the *oldest* messages,
  which are the system prompt and the rules. The loop prevents this by shortening the oldest tool
  results once the estimated size passes 75% of `num_ctx`. Ids that were cited stay valid.
- **Fallback for tool calls written as text.** Small models sometimes write a tool call as plain text
  (`<tool_call>{…}</tool_call>`) instead of a structured call; these are parsed and run.

**Stance and confidence.** The stance is *relative to the benchmark*: bullish means the model expects the
ticker to beat SPY over the horizon. This matches how M10 will score suggestions (excess return).
`confidence` is the probability that the stance turns out right; the prompt tells the model to stay
cautious, and M10 will check how well this matches reality [[22]](references.md#ref-22).

**Weekly run** ([orchestration/weekly_run.py](../orchestration/weekly_run.py)) works through the
watchlist:
1. Checks that the Ollama model exists.
2. Opens an `agent_runs` row.
3. Runs each ticker, with one retry that keeps any horizon already saved.
4. Closes the run as `ok`, `partial` or `error`.
5. Sends the Telegram digest ([delivery/telegram.py](../delivery/telegram.py)), or an alert if the run
   failed. Messages are plain text and split to stay under Telegram's 4096-character limit.

[scripts/register_weekly_task.ps1](../scripts/register_weekly_task.ps1) schedules the run in Windows
Task Scheduler (Saturday 09:00 by default; if the PC was off, it runs when it's next on).

**Remaining lookahead risk.** With a past `--as-of`, every input is still limited to data from before
that date, but the LLM's training data may contain hindsight [[3]](references.md#ref-3). Backtests
with dates before the model's training cutoff should be treated as optimistic.

## 8. Website (M9, Django)

[web/](../web/) is a server-rendered Django site. Data comes from Supabase through a read-only `Repo`
([web/dashboard/repo.py](../web/dashboard/repo.py)) that uses the same `Store` as the pipeline. The
service key stays on the server. Django's SQLite database holds only users and sessions, which keeps
access invite-only (the README's guardrail on MAR exposure) without a public sign-up flow.

- **Escaping.** Everything the LLM writes passes through Django's auto-escaping, and links to sources are
  rendered only for `http(s)` URLs.
- **Chart.** The price chart shows the ticker and the benchmark indexed to 100, because their prices are
  on different scales and should never share a dual axis. Chart.js 4.4.1 loads from cdnjs with an SRI
  hash. Colours come from a validated two-series palette for light and dark mode, the lines carry direct
  end labels, hovering shows a crosshair and tooltip, and a month-end table gives the same data without
  the chart.
- **Caching.** Features are cached for 10 minutes per ticker per day.
- **Scroll story.** The home page uses no animation library. On wide, tall screens each ticker scene
  pins for about 1.4 screens of scrolling while a script maps scroll position to CSS variables (0 to 1)
  that drive the symbol, the two views and the exit fade, like scrubbing a video. A scene whose content
  can't fit one screen just scrolls normally. On phones and short windows elements fade up as they
  appear instead. With `prefers-reduced-motion` or no JavaScript, it's a plain page with everything
  visible. Each view is compared with the previous good run and marked new, changed or unchanged.

The Flutter app will read the same tables directly with the anon key and Supabase Auth, under the
`authenticated` policies in `db/rls.sql`.

## 9. Later phases (planned)

| Phase | Module | Approach | References |
|---|---|---|---|
| P5 | M7 portfolio | QAOA on a binary asset-selection problem (QUBO), compared with classical solvers | QAOA [[19]](references.md#ref-19), QAOA portfolio benchmark [[20]](references.md#ref-20) |
| P5 | M7 regime classifier | Quantum-kernel SVM on macro and price features | Havlíček et al. [[21]](references.md#ref-21) |
| P5 | M10 evaluation | Hit rate, excess return, **calibration** of `confidence`, citation faithfulness | Guo et al. [[22]](references.md#ref-22), Gao et al. [[15]](references.md#ref-15) |
