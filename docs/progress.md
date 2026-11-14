# Progress report

*Status as of 2026-11-14.* For how the parts work, see [architecture.md](architecture.md). For the
threat model, see [security.md](security.md). For the full write-up, see the report ([report/](report/)) and
the paper ([paper/](paper/)).

## Summary

| Phase | What it covers | Code | Gate | Gate status |
|---|---|---|---|---|
| P1 Foundations | Ingestion, processing, storage (M1–M3) | Done | 7 days of data without errors | **Restarted 2026-11-14** after the move to local PostgreSQL. Full first load done with 0 errors; earliest pass **2026-11-21** |
| P2 Knowledge | Quant engine, hybrid retrieval (M4–M5) | Done | Relevant chunks on 10 test queries | **Passed 2026-11-11.** 10/10 automatic checks; 10/10 on-topic by manual review with rerank |
| P3 Agent | Agent, weekly run, Telegram (M6, M8, M9) | Done | 4 weekly runs of valid, cited JSON | **1 / 4.** Week of 2026-11-14: `ok`, 40 views for 20 picks |
| Web | Django dashboard (M9 web) | Done | — | Runs locally against the database |
| App | Flutter client on GitHub Pages | Done (21 tests) | — | **Live** at `https://nsskn982.github.io/TI-Agent/`, reading the encrypted `data.json` |
| P5 Evaluation | M10 scoring, baselines, faithfulness | Done (11 tests) | Primary analysis: 12 closed weeks at 63 trading days | **0 / 12.** First full and baseline views saved; the first 21-day outcomes close on 2026-12-15 |
| P5 Quantum | M7 QAOA portfolio | Not started | Quantum vs classical report | — |

**Tests:** 148 Python tests and 21 Flutter tests, all passing offline (no network or keys needed).

## 2026-11-14: what changed

- **Local database.** Supabase is gone. Everything runs on PostgreSQL 17 + pgvector in Docker
  (`127.0.0.1:5433`) through [common/store.py](../common/store.py) (psycopg 3). The Supabase data was not
  migrated, so the first load was run again.
- **Schedules.** GitHub Actions can't reach a local database, so the jobs are now Windows scheduled tasks
  ([scripts/register_tasks.ps1](../scripts/register_tasks.ps1)). All four are registered: daily refresh,
  weekly screen, weekly AI run and the weekly evaluation baseline (`-WithBaseline`).
- **Refresh and retention.** After the first load only new data is downloaded
  ([ingestion/refresh.py](../ingestion/refresh.py)). The weekly screen deletes data no module reads any
  more ([orchestration/retention.py](../orchestration/retention.py)).
- **App delivery without a server.** Each run exports what the app shows into one AES-256-GCM file,
  `site-data/data.json` ([orchestration/export_app.py](../orchestration/export_app.py)). You push the file
  and the app decrypts it in the browser. The local API, the tunnel and Supabase Auth are gone.
- **Live progress in the terminal.** Every run script shows its steps live ([common/progress.py](../common/progress.py)).
  The details go to `logs\`.
- **M10 evaluation** ([evaluation/](../evaluation/)): outcomes, the four comparators, metrics and the report.
  It runs at the end of every weekly screen.
- **Agent variants.** `weekly_run --variant no_retrieval` runs the same agent with document search turned
  off. It is the evaluation's retrieval ablation and is never published.
- **Company names.** The dashboard, the app (glance cards, ticker scenes, the Compare table, ticker page
  titles) and the exported data show company names next to tickers. Names come from the screen's Wikipedia
  list and are tidied for display by `company_name()` in [common/text.py](../common/text.py). The daily
  refresh no longer overwrites them with SEC registrant names such as `VALERO ENERGY CORP/TX`.
- **Robustness.** Filing downloads are streamed and capped at 25 MB. Processing stops cleanly when memory
  runs out. Ollama unloads the model after each run.
- **Documentation.** There is a technical report ([report/main.tex](report/main.tex), 18 pages) and a
  journal-style paper ([paper/paper.tex](paper/paper.tex), elsarticle), both with TikZ figures.

## Data loaded (2026-11-14)

| Data | Rows | | Data | Rows |
|---|---|---|---|---|
| Tickers (S&P 500 + 400, SPY) | 904 | | Documents | 5,475 (4,875 news, 600 filings) |
| Daily prices | 495,468 | | Chunks with embeddings | 37,879 |
| Fundamentals (XBRL facts) | 429,924 | | Macro observations | 428 |
| Screen rows | 903 | | Database size | 438 MB |

Filings: 444 8-K, 117 10-Q and 39 10-K. News comes from Finnhub's feed: Yahoo, Benzinga, SeekingAlpha,
ChartMill, Fintel, CNBC and others.

## Phase 2 gate: retrieval quality

`python -m retrieval.evaluate` (2026-11-11, k = 5):

| Mode | Automatic checks | On-topic top results (manual review) |
|---|---|---|
| Hybrid (vector + keyword) | 10/10 | about 7/10; weaker on AAPL China, NVDA export controls, GOOGL YouTube |
| Hybrid + cross-encoder rerank | 10/10 | 10/10 |

The agent's `search_knowledge` therefore reranks by default (about 0.5 s per query on CPU).

## Weekly screen, week of 2026-11-14

903 stocks screened, 728 passed the quality filter, top 20 kept. New picks get two years of news and
filings, then embeddings.

## Phase 3 and evaluation: AI runs, week of 2026-11-14

| Run | Variant | Result | Time | Saves rejected by the guardrails | Citations |
|---|---|---|---|---|---|
| `agent_runs` #1 | `full` | **`ok`**: 20 picks, 40 views | 32 min | 49 of 89 | 152 |
| `agent_runs` #2 | `no_retrieval` | **`ok`**: 20 picks, 40 views | 31 min | 73 of 113 | none (by design) |

| Stances | 1–3 months (bull / neutral / bear) | 6–24 months (bull / neutral / bear) | Mean confidence |
|---|---|---|---|
| Full | 17 / 2 / 1 | 13 / 6 / 1 | 0.59 |
| No retrieval | 14 / 6 / 0 | 12 / 6 / 2 | 0.59 |

The two variants agreed on 13 of 20 stances at each horizon. Cohen's κ is **0.07** for 1–3 months and
**0.32** for 6–24 months. So document search changes the short-horizon calls much more than the long ones.
This is one week, and whether either variant is *right* is unknown until the outcomes close.

**Why so many saves were rejected:**

- **Full run:** 26 of the 49 were figures not found in any tool output, and 23 were missing fields
  (bull case, bear case, stance or thesis). In every case the model corrected the save and tried again.
- **No-retrieval run:** most rejections were period labels. In "3m momentum", the number check reads "3m"
  as "3 million" and finds no such number in the tool output. That was a false positive. It cost steps but
  no views: 3 tickers needed a second attempt. **Fixed on 2026-11-14, after week 1** (see below).

**Evaluation report** (`reports/evaluation.md`): 1 week of views, 0 of 12 weeks closed, marked preliminary.
120 view outcomes and 2,304 baseline outcomes are waiting for their windows to close. The first closes are
21 trading days after 2026-11-14.

Gate query (`docker exec -it ti-agent-db psql -U ti_agent`):

```sql
select r.id, r.as_of, r.variant, r.status, count(s.id) as suggestions,
       count(*) filter (where cardinality(s.sources) > 0) as cited
from agent_runs r left join suggestions s on s.run_id = r.id
group by r.id order by r.id desc limit 8;
```

## Earlier runs (Supabase era, 5-stock watchlist)

| Run | Result | Notes |
|---|---|---|
| #1 | `error`, no suggestions | Windows ran out of commit memory, so Ollama couldn't load the model. It failed cleanly and saved nothing invalid |
| #2 | `ok`: 5 tickers, 10 views, 4 min | The model now loads first and stays loaded. Loads that fail for lack of memory are retried |

These quality fixes came from reading the theses:

- **Fixed:** "50%" was accepted because `sma_50` is a field *name*. Now only JSON values count, and dates are ignored.
- **Fixed:** non-English text (one risk line was partly in Chinese) is rejected.
- **Open:** real numbers sometimes carry the wrong label. This is measured by the M10 citation-faithfulness annotation.

## Website and app

- **Django dashboard** ([web/](../web/)), local only:
  - `/` is a scroll story of this week's picks, with company names.
  - `/t/<ticker>/` shows the 12-month chart against SPY, the features and the history.
  - `/c/<id>/` shows a cited passage.
  - `/status/` shows the runs.
- **Flutter app** ([app/](../app/)): one codebase for web, Android and iOS. It is published to GitHub Pages
  by [.github/workflows/app.yml](../.github/workflows/app.yml), which copies `site-data/data.json` in as
  `data/data.json`. Opening it asks for the password once; after that the device remembers the derived key.

## Next steps

1. **Push** `site-data/data.json` after each run, or the app keeps showing the last pushed week.
2. ~~Fix the "3m" false positive~~ **Done 2026-11-14**, before the second week. In
   [agent/schema.py](../agent/schema.py), a whole number of at most 60 written directly against "m" with no
   `$` sign (`1m`, `3m`, `6M`, `12m`) is treated as a period in months and isn't checked. `$3m`, `3.5m`,
   `250m` and `3 m` are still checked as millions. Week 1 ran under the old check, and the paper records
   the change as a protocol amendment. 13 of the 26 number rejections in the full run and 51 of the 71 in
   the no-retrieval run would have passed under the new rule.
3. Let the scheduled tasks run. That gives Phase 1 (7 clean days, around 2026-11-21) and Phase 3 (4 weekly
   runs, around 2026-12-05).
4. First faithfulness annotation, after 4 weeks: `python -m evaluation.faithfulness sample --n 60`. Two
   annotators then score it with `score`.
5. Primary evaluation after 12 closed weeks at 63 trading days, around May 2027.
6. Phase 5 quantum: the QAOA portfolio experiment against a classical optimiser.
7. Optional: set up the Telegram bot (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), and an Android APK for testers.

## Known limitations

| Limitation | Impact | Possible fix |
|---|---|---|
| The model needs about 4.6 GB of commit memory; the page file is fixed at 6–12 GB | Runs fail with cudaMalloc errors when browsers are open | Close heavy apps before the Saturday runs |
| The app is as fresh as the last push | Readers see old data if you forget to push | Push after each run (automating it would need a token on the laptop) |
| Finnhub free tier: about 1 year of news, headline and summary only | No full article text; short history | Add GDELT or RSS feeds |
| Filings cut off at 300k characters | The end of a very long 10-K can be lost | Extract Item 1A / Item 7 |
| 8-Ks: main document only | The press release (EX-99.1) is missed | Fetch EX-99 exhibits |
| Some XBRL tags not on our list | Some ratios are `null` | Add fallback tags as they turn up |
| FRED values have no release timestamp | Release delays are conservative estimates | Use ALFRED vintages |
| A 4B model sometimes mislabels numbers | Thesis wording can be wrong even when the number is real | M10 faithfulness evaluation; a larger model when hardware allows |
| One week of views | No evaluation results yet | Time: the primary analysis needs 12 closed weeks |
