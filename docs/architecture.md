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

## 7. Later phases (planned)

| Phase | Module | Approach | References |
|---|---|---|---|
| P3 | M6 agent | A loop where the model alternates reasoning and tool calls, capped at a fixed number of steps; read-only tools plus `save_suggestion` | ReAct [[16]](references.md#ref-16), Toolformer [[17]](references.md#ref-17), Qwen2.5 [[18]](references.md#ref-18) |
| P5 | M7 portfolio | QAOA on a binary asset-selection problem (QUBO), compared with classical solvers | QAOA [[19]](references.md#ref-19), QAOA portfolio benchmark [[20]](references.md#ref-20) |
| P5 | M7 regime classifier | Quantum-kernel SVM on macro and price features | Havlíček et al. [[21]](references.md#ref-21) |
| P5 | M10 evaluation | Hit rate, excess return, **calibration** of `confidence`, citation faithfulness | Guo et al. [[22]](references.md#ref-22), Gao et al. [[15]](references.md#ref-15) |
