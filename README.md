# TI Agent — Trading Intelligence

An agentic, retrieval-augmented AI that screens about 900 US stocks every week (the **S&P 500** large caps plus the **S&P MidCap 400**). For the **top 20** picks it writes a **medium-term (1–3 months)** and a **long-term (6–24 months)** analysis: thesis, bull and bear case, catalysts, valuation and risks. Every analysis is grounded in news, SEC filings, macro data and price history, and every claim is cited.

Everything runs on **your own laptop** with **free tools**: a local PostgreSQL + pgvector database, a local LLM (Ollama), and Windows scheduled tasks. A **quantum computing** research layer for portfolio optimisation is planned.

> **Disclaimer:** TI Agent is a research and learning project. Its output is not financial advice. It never places trades. Use at your own risk.

---

## Contents

1. [How it works in one picture](#how-it-works-in-one-picture)
2. [The phases](#the-phases)
   - [Phase 1: Foundations (collect and store data)](#phase-1-foundations-collect-and-store-data)
   - [Phase 2: Knowledge (numbers and search)](#phase-2-knowledge-numbers-and-search)
   - [The weekly stock screen (choosing what to analyse)](#the-weekly-stock-screen-choosing-what-to-analyse)
   - [Phase 3: Agent (the AI analyst)](#phase-3-agent-the-ai-analyst)
   - [Phase 4: App (showing the results)](#phase-4-app-showing-the-results)
   - [Phase 5: Quantum and evaluation (planned)](#phase-5-quantum-and-evaluation-planned)
3. [Data lifecycle: first run, refreshes, retention](#data-lifecycle-first-run-refreshes-retention)
4. [Setup](#setup)
5. [Running it every week](#running-it-every-week)
6. [Publishing the app on GitHub Pages](#publishing-the-app-on-github-pages)
7. [Reference](#reference): dashboard, API, environment variables, repository layout, guardrails, documentation

---

## How it works in one picture

```text
                     ┌──────────────────────── your laptop ─────────────────────────┐
 Wikipedia, yfinance │  Weekly screen (Sat 01:30)   ~900 stocks → top 20 picks       │
 SEC EDGAR + XBRL    │  Daily refresh (weekdays)    new prices, news, filings, macro │
 Finnhub, FRED  ───► │        │ chunk · embed (MiniLM) · score news (FinBERT)        │
                     │        ▼                                                      │
                     │  PostgreSQL 17 + pgvector  (Docker, 127.0.0.1:5433)           │
                     │        ▲            │                                         │
                     │        │            ▼                                         │
                     │  AI agent (Sat 09:00)       Django dashboard (local only)      │
                     │  Ollama · Qwen3.5 4B                                          │
                     │        │ after each run: export → site-data/data.json         │
                     └────────│──────────── (AES-256-GCM, password-encrypted) ───────┘
                              │ you push it
                              ▼
   Telegram digest      GitHub Pages: Flutter app + data/data.json → decrypted in the browser
                                      with the password · Android APK
```

The database is the single hand-off point. Every module reads from and writes to it through one file,
[common/store.py](common/store.py), so each part can be developed, tested and replaced on its own. The
tests swap the database for an in-memory fake ([tests/fakes.py](tests/fakes.py)) and need no network or keys.

**Modules.** The code is split into ten modules (M1–M10). The phases below group them.

| # | Module | Folder | Phase |
|---|---|---|---|
| M1 | Ingestion | [ingestion/](ingestion/) | 1 |
| M2 | Processing + embedding | [processing/](processing/) | 1 |
| M3 | Knowledge store | [db/](db/), [common/store.py](common/store.py) | 1 |
| M4 | Quant engine + weekly screen | [quant/](quant/) | 2 |
| M5 | Retrieval | [retrieval/](retrieval/) | 2 |
| M6 | AI finance agent | [agent/](agent/) | 3 |
| M7 | Portfolio + quantum | `portfolio/` (planned) | 5 |
| M8 | Orchestration | [orchestration/](orchestration/), `run_*.cmd` | 1–3 |
| M9 | Delivery: Telegram, website, app | [delivery/](delivery/), [web/](web/), [app/](app/) | 3–4 |
| M10 | Evaluation | `evaluation/` (planned) | 5 |

---

## The phases

Each phase has a **gate**: a measurable condition that must hold before the next phase builds on it.

| Phase | What it delivers | Gate | Status (2026-11-14) |
|---|---|---|---|
| **P1 Foundations** | Data collected daily and stored locally | 7 consecutive daily runs without errors | Code done. Restarting on the local database: needs a fresh backfill |
| **P2 Knowledge** | Computed features + hybrid search | Relevant passages for 10 test queries | **Passed** (10/10 with rerank) |
| **Screen** | Top 20 of ~900 stocks each week | — | Code done; first full run pending |
| **P3 Agent** | Weekly cited suggestions + Telegram | 4 weekly runs of valid, cited JSON | 1 of 4 |
| **P4 App** | Flutter app (web, Android, iOS) | Testers with the password for 2 weeks | Code and data export done; push to publish |
| **P5 Quantum + evaluation** | QAOA portfolio, scoring of past suggestions | Quantum vs classical benchmark report | Not started |

### Phase 1: Foundations (collect and store data)

**Goal:** a reliable, point-in-time record of everything the analyst may look at: prices, company news,
SEC filings, financial statements and macro data.

**M1 Ingestion** ([ingestion/run.py](ingestion/run.py)) pulls five sources for each ticker. Each source and
ticker is isolated: one failure is logged and the rest carry on.

| Source | Module | What is stored | Notes |
|---|---|---|---|
| yfinance | [prices.py](ingestion/prices.py) | Daily OHLCV + adjusted close, plus the benchmark (`SPY`) | ~800 days on the first run, then only new days |
| Finnhub | [finnhub.py](ingestion/finnhub.py) | News headline + summary (`documents`, `source='news'`) | Free tier: ~1 year of history, 60 calls/min |
| SEC EDGAR | [edgar.py](ingestion/edgar.py) | Text of 10-K, 10-Q and 8-K filings (`source='filing'`) | Already-stored filings are skipped |
| SEC XBRL | [fundamentals.py](ingestion/fundamentals.py) | Every financial fact as reported in each filing (`fundamentals`) | Lets the quant engine rebuild what was known on any date |
| FRED | [fred.py](ingestion/fred.py) | 8 macro series (rates, CPI, unemployment, …) | Free API key |

**M2 Processing** ([processing/run.py](processing/run.py)) turns new documents into searchable knowledge:

1. **Chunking:** text is split at sentence boundaries into chunks of ≤ 180 words with 30 words of overlap.
   This fits the 256-token limit of the embedding model. A news item stays one chunk.
2. **Embedding:** `all-MiniLM-L6-v2` turns each chunk into a 384-number vector, prefixed with
   `"AAPL 10-K: …"` so that passages from different companies stay apart.
3. **Sentiment:** FinBERT scores each news item from −1 (negative) to +1 (positive).

**M3 Knowledge store** ([db/schema.sql](db/schema.sql)) is a local **PostgreSQL 17 with pgvector**, run in
Docker ([docker-compose.yml](docker-compose.yml)). Chunks have an HNSW vector index and a full-text
(`tsvector`) index. Two SQL functions, `match_chunks` and `keyword_chunks`, do the searching.

**The no-lookahead rule.** Everything carries the timestamp at which it became *public*: prices by
trading day, filings by SEC acceptance time, XBRL facts by filing date, and macro values by observation
date plus a release delay. Every read asks for data strictly **before** an `as_of` date. This prevents
the system from "knowing the future" in backtests.

**Run it:** `run_daily.cmd` (ingest + process). The first time, use `run_daily.cmd --days 730` for a
two-year backfill.

**Gate:** 7 consecutive daily runs with status `ok` in `ingestion_runs` (shown on the dashboard's
`/status/` page).

### Phase 2: Knowledge (numbers and search)

**Goal:** give the analyst two kinds of evidence, **numbers computed by code** and **relevant passages
found by search**, so the LLM never has to invent either.

**M4 Quant engine** ([quant/](quant/)) computes, as of any date:

- **Technicals** ([indicators.py](quant/indicators.py)): 1/3/6/12-month returns, 50- and 200-day averages,
  RSI(14), MACD, volatility, max drawdown, distance from 52-week high/low, beta and relative strength vs `SPY`.
- **Point-in-time fundamentals** ([fundamentals.py](quant/fundamentals.py)): quarterly figures derived from
  as-reported SEC facts, trailing-twelve-month (TTM) revenue, earnings and free cash flow, year-on-year
  growth, margins, P/E, FCF yield and debt-to-equity. Each figure uses only filings made before the as-of date.
- **News sentiment** ([sentiment.py](quant/sentiment.py)): 7/30/90-day averages, trend and news-volume z-score.
- **Macro** ([macro.py](quant/macro.py)): latest value of each series after its release delay, plus recent changes.

**M5 Retrieval** ([retrieval/search.py](retrieval/search.py)) finds the passages that answer a question:

1. **Vector search** (meaning) and **keyword search** (exact terms like "Blackwell" or "Item 1A") each return candidates.
2. **Reciprocal Rank Fusion** merges the two lists without any tuning.
3. An optional **cross-encoder rerank** re-scores the best candidates (this is what passed the gate).
4. **Diversity:** at most 2 chunks per document, so one long 10-K can't fill every slot.
5. Every hit carries a `chunk_<id>` **citation** that the agent must quote.

Both are also available as a local HTTP API (see [Reference](#quant--retrieval-api)).

**Gate:** `python -m retrieval.evaluate --rerank` runs 10 test queries. For each one it checks that the
results have the right ticker and source, that none is dated after `as_of`, and that an expected keyword
appears. **Passed 2026-11-11: 10/10.**

### The weekly stock screen (choosing what to analyse)

**Goal:** analyse the *most promising* stocks instead of a hand-picked list, within a laptop's budget.
Running retrieval and the LLM on 900 stocks would take over 10 GPU-hours a week, so the pipeline filters
in two stages:

1. **Screen everything cheaply** ([orchestration/screen_run.py](orchestration/screen_run.py), [quant/screen.py](quant/screen.py)):
   - The S&P 500 and S&P 400 member lists come from Wikipedia.
   - Prices for every stock and SEC fundamentals for every company are updated (incrementally after the first run).
   - **Quality filter:** latest quarter < 200 days old, TTM net margin > 0, TTM free cash flow > 0.
   - **Momentum score** among the stocks that pass: 0.50·z(12-1-month return) + 0.25·z(6-month return vs SPY)
     \+ 0.25·z(3-month return vs SPY) − 0.20·z(6-month volatility).
   - Results go to `screens`, and the top 20 are marked `selected`.
2. **Analyse only the picks.** A new pick gets two years of news and filings, which are then chunked, embedded
   and scored. From then on, the daily refresh and the weekly agent work on the picks automatically.
   `watchlist.txt` is used only before the first screen.
3. **Clean up:** at the end of the screen, data no module reads any more is deleted
   (see [Retention](#retention-only-useful-data-is-kept)).

**Run it:** `run_screen.cmd`. The first run takes about 1.5–2 hours because it downloads about 4–5 GB from the SEC. Later runs
download only what is new.

### Phase 3: Agent (the AI analyst)

**Goal:** for each pick, a structured, cited view for two horizons, written by a local LLM that
gathers its own evidence.

**M6 Agent** ([agent/](agent/)) runs **Qwen3.5 4B** in Ollama (a text-only build that fits a 6 GB GPU,
made by [scripts/create_model.ps1](scripts/create_model.ps1)) with "thinking" switched on. For each ticker it
loops (reason → call a tool → read the result) until both suggestions are saved:

| Tool | Kind | What it returns |
|---|---|---|
| `search_knowledge` | read | Up to 6 cited passages from Phase 2 retrieval |
| `get_features` | read | Technicals, fundamentals and sentiment from the quant engine |
| `get_prices` | read | Weekly closes (≤ 52 weeks) |
| `get_macro` | read | Macro snapshot |
| `save_suggestion` | **write** (the only one) | Validates and stores a suggestion, or tells the model what to fix |

**Guardrails enforced in code** (a small model doesn't reliably follow prompt rules):

- `ticker` and `as_of` are filled in by code, and the model can't change them.
- Every cited `chunk_<id>` must have come back from a search in the same conversation.
- Every number in the text must match a value some tool returned.
- At most 12 model turns and 16 tool calls per ticker. Every call is logged in `tool_calls`.
- The stance is *relative to the S&P 500*: bullish means "expected to beat SPY".

A saved suggestion looks like this (plus bull case, bear case, catalysts and valuation):

```json
{
  "ticker": "AAPL", "horizon": "long", "stance": "bullish",
  "thesis": "Short explanation grounded in cited sources.",
  "risks": ["Risk one", "Risk two"],
  "sources": ["chunk_1842", "chunk_1907"],
  "confidence": 0.62, "as_of": "2026-11-14"
}
```

**M8 Weekly run** ([orchestration/weekly_run.py](orchestration/weekly_run.py)) opens an `agent_runs` row,
analyses each pick (with one retry), and closes the run as `ok`, `partial` or `error`. **M9 Telegram**
([delivery/telegram.py](delivery/telegram.py)) then sends a digest, or an alert if the run failed.

**Run it:** double-click `run_weekly.cmd` (about 30 minutes for 20 picks). Close browsers first: the
model needs about 5 GB of free memory.

**Gate:** 4 weekly runs in which every suggestion is valid and cited.

### Phase 4: App (showing the results)

**Goal:** let the people you choose read the results on the web and on their phones.

- **Flutter app** ([app/](app/)), one codebase for web, Android and iOS:
  - **Home:** this week's picks in rank order, each with its daily figures and why it made the list.
  - **Compare:** a sortable table of all picks.
  - **Ticker pages:** a chart vs the S&P 500, suggestion history, and the cited passages.
  - The web build is published on **GitHub Pages** by [.github/workflows/app.yml](.github/workflows/app.yml),
    which also builds an Android APK.
- **Encrypted data file** ([orchestration/export_app.py](orchestration/export_app.py)): GitHub Pages hosts
  only files, so after each run the laptop exports what the app shows into one file, `site-data/data.json`.
  It is encrypted with a password you choose (AES-256-GCM, key from PBKDF2-SHA256). You push it, the
  workflow publishes it beside the app, and the app decrypts it in the browser. The site needs no server,
  tunnel or domain, and works while your laptop is off. See
  [Publishing the app](#publishing-the-app-on-github-pages).
- **Django dashboard** ([web/](web/)): the owner's local research view with pipeline status and the computed
  features the agent saw.

**Gate:** testers with the password use the app for 2 weeks.

### Phase 5: Quantum and evaluation (planned)

- **M7 Portfolio + quantum:** turn the suggestions into portfolio weights and compare a classical
  mean-variance optimiser against **QAOA** on a quantum simulator (Qiskit / PennyLane). Results go to `portfolio_runs`.
- **M10 Evaluation:** score every past suggestion against what actually happened:
  - hit rate at 1, 3 and 12 months
  - excess return vs SPY
  - calibration (higher confidence should mean a higher hit rate)
  - citation faithfulness (claims match their sources)

  Results go to `performance`.

**Gate:** a report benchmarking quantum vs classical (objective value and runtime).

---

## Data lifecycle: first run, refreshes, retention

### First run, then refreshes

| Data | First run | Later runs |
|---|---|---|
| Prices | ~800 days per ticker | Only days after the last stored one (with a 1-week overlap). If a dividend or split has re-based the adjusted closes, that ticker is re-fetched in full |
| Fundamentals (SEC XBRL) | ~4 years of filings | Only filings since the last stored one (30-day overlap for amendments) |
| News | Up to 1 year for a new pick | The last few days (`--days`, default 5) |
| Filings | 2 years for a new pick | New filings only (already-stored filings are skipped) |
| Macro | ~120 days minimum | Same window, upserted |
| Chunks, embeddings, sentiment | All new documents | Only documents not yet processed or scored |

The logic is in [ingestion/refresh.py](ingestion/refresh.py). A ticker whose data is missing, too short or
more than 30 days stale is backfilled automatically, so a laptop that was off for a while catches up by itself.

### Retention: only useful data is kept

At the end of every weekly screen, [orchestration/retention.py](orchestration/retention.py) deletes what no
module reads any more. Each window matches the longest look-back of the code that reads that table:

| Data | Kept for | Why |
|---|---|---|
| Prices | 800 days | Backfill window (the screen needs 420 days, features 400) |
| Fundamentals | Filed in the last ~4 years | 2-year analysis + 2 years for year-ago TTM figures |
| Macro | 600 days | 500-day look-back + release delays |
| News | 400 days | Finnhub serves ~1 year; sentiment uses 91 days |
| Filings | 800 days | 2-year backfill |
| Screens | 400 days | History on the dashboard and in the app |
| Tool-call and ingestion logs | 180 days | Debugging and audit |

It also does the following:

- **Documents and chunks** are deleted for tickers that aren't on the watchlist and haven't been picked in
  the last 8 weeks. They're backfilled again if the stock comes back.
- **Tickers** that left both indexes, aren't on the watchlist and were never suggested are removed.
- **Full filing and news text** is cleared once it's been chunked and scored. The chunks keep everything the search uses.
- **Chunks cited by any suggestion are never deleted**, so every citation keeps working.

Run it by hand with `python -m orchestration.retention` (`--dry-run` shows the cut-off dates), or skip it
for one screen with `run_screen.cmd --keep-old`.

---

## Setup

**Requirements:**

- Windows 10/11 (the pipeline is plain Python, so Linux and macOS work with the `python -m …` commands)
- Python 3.11+ and Docker Desktop
- An NVIDIA GPU with ≥ 6 GB VRAM for `qwen3.5:4b` (`qwen3.5:2b` works on smaller GPUs or CPU)
- About 5 GB of free memory during the weekly run
- Free accounts: Finnhub, FRED, Telegram (optional), and GitHub (for the app on GitHub Pages)
- Flutter SDK, only to build the app locally

```powershell
# 1. Clone and install (creates .venv, installs requirements, creates .env, builds the model)
git clone https://github.com/nsskn982/TI-Agent.git
cd TI-Agent
.\scripts\setup.ps1                 # -OllamaModel qwen3.5:2b for a smaller GPU; -SkipOllama for Python only

# 2. Fill in .env: FINNHUB_API_KEY, FRED_API_KEY, SEC_USER_AGENT ("Name email"), optional Telegram

# 3. Start the database and create the schema (both safe to re-run)
docker compose up -d                # PostgreSQL 17 + pgvector on 127.0.0.1:5433, data in a Docker volume
.venv\Scripts\python -m common.db_init

# 4. First load (the long one)
run_screen.cmd                      # ~1.5-2 h: index members, prices, SEC fundamentals, top 20, backfill picks
run_daily.cmd --days 730            # 2-year backfill of everything for the picks

# 5. Check it
.venv\Scripts\python -m pytest -q                   # offline tests, no keys or database needed
.venv\Scripts\python -m retrieval.evaluate --rerank # Phase 2 gate
run_weekly.cmd --tickers AAPL --no-telegram         # one-ticker agent smoke test
```

Recommended Ollama settings for 6 GB of VRAM (`setup.ps1` sets them): `OLLAMA_FLASH_ATTENTION=1`,
`OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_CONTEXT_LENGTH=16384`. Keep `OLLAMA_HOST` at `127.0.0.1`.

**Database notes:**

- The container listens on **127.0.0.1 only**. Port 5433 is used so it doesn't clash with a native
  PostgreSQL on 5432. To use another server, set `DATABASE_URL`; it needs the `vector` extension.
- To change the password, set `POSTGRES_PASSWORD` *before* the first `docker compose up`, and update
  `DATABASE_URL` to match.
- Back up with `docker exec ti-agent-db pg_dump -U ti_agent ti_agent > backup.sql`.

## Running it every week

Register the jobs once:

```powershell
.\scripts\register_tasks.ps1        # -Unregister removes them; times are parameters
```

| Task | When (local time) | Script | Does |
|---|---|---|---|
| TI-Agent daily refresh | Weekdays 23:45 | `run_daily.cmd` | New prices, news, filings, fundamentals, macro → chunk, embed, score |
| TI-Agent weekly screen | Saturday 01:30 | `run_screen.cmd` | Screen ~900 stocks → top 20, backfill new picks, retention |
| TI-Agent weekly run | Saturday 09:00 | `run_weekly.cmd` | AI suggestions for the picks → Telegram digest |

- Each script starts Docker Desktop and the database container if they aren't running.
- Each script writes to `logs\` (`daily_run.log`, `screen_run.log`, `weekly_run.log`).
- Each script ends by updating the app's data file, `site-data/data.json`. **Push it** to publish the new data.
- In a terminal each script shows its steps live; detailed log lines go to the log file.
- A run missed because the PC was off starts when it's next on.
- The tasks run only while you're logged on.

---

## Publishing the app on GitHub Pages

GitHub Pages hosts only files, so the app can't reach the database on your laptop. Instead, every run
exports what the app shows into one encrypted file, `site-data/data.json`: this week's picks, the AI views
(and last week's, to mark what changed), a year of prices and the cited passages. You push it; the app on
GitHub Pages downloads it and decrypts it in the browser with the password. Nothing runs online, and the
app works while your laptop is off. It is as fresh as your last push.

1. **Choose the password.** `APP_DATA_PASSWORD` in `.env` (setup already put a random one there). Give it
   only to the people who may read the app. Changing it re-encrypts the file at the next run, and everyone
   has to enter the new one.
2. **Export** (each run does this at the end; to do it by hand):
   ```powershell
   .venv\Scripts\python -m orchestration.export_app           # writes site-data\data.json if anything changed
   .venv\Scripts\python -m orchestration.export_app --check   # decrypts it and prints what's inside
   ```
3. **Turn on GitHub Pages once:** *Settings → Pages → Source: GitHub Actions*.
4. **Push** `site-data/data.json` (with your code, or on its own after a run). The *App (Flutter)* workflow
   tests the app, builds it, puts the data file next to it and publishes `https://<github-user>.github.io/TI-Agent/`.
   The Android APK is attached to the workflow run; it reads the same file from that address.

**About privacy.** A GitHub Pages site is public: anyone can download `data.json`, but without the password
it is unreadable. Because anyone can try passwords on it offline, use a long random password (the default
is 24 random characters) and don't reuse it elsewhere. The password never leaves the device: the app
derives the key locally and remembers only the key, until the password changes.

For local app development, copy [app/config.example.json](app/config.example.json) to `app/config.json`
(it reads the published file) and run `flutter run -d chrome --dart-define-from-file=config.json`.

---

## Reference

### Dashboard (Django, local)

```powershell
.venv\Scripts\python web\manage.py runserver      # http://127.0.0.1:8000 (needs DJANGO_DEBUG=true in .env)
```

| Page | Shows |
|---|---|
| `/` | Scroll story of this week's picks: both views per ticker, marked **New** / **Changed from …** |
| `/t/<ticker>/` | 12-month chart vs the benchmark, the features the agent saw, suggestion history |
| `/c/<chunk_id>/` | The exact cited passage, with a link to the original filing or article |
| `/status/` | Roadmap gates, agent runs, ingestion and processing runs |

### Quant + retrieval API

`.venv\Scripts\uvicorn quant.api:app --port 8000` (docs at `/docs`). It answers only requests from this
machine, unless `QUANT_API_TOKEN` is set; then each request needs `Authorization: Bearer <token>`.

| Route | Returns |
|---|---|
| `GET /features/{ticker}?as_of=` | Technicals, point-in-time fundamentals, sentiment aggregates |
| `GET /prices/{ticker}?as_of=&days=` | Daily bars |
| `GET /macro?as_of=` | FRED snapshot with release delays applied |
| `GET /search?q=&ticker=&source=&as_of=&k=&rerank=` | Hybrid search, each hit with a `chunk_<id>` citation |

### Environment variables (`.env`, never committed)

| Variable | Used by |
|---|---|
| `DATABASE_URL`, `POSTGRES_PASSWORD` | Everything (default `postgresql://ti_agent:ti_agent@127.0.0.1:5433/ti_agent`) |
| `FINNHUB_API_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT` | Ingestion (EDGAR needs a contact email in the user agent) |
| `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_THINK` | Agent |
| `BENCHMARK`, `SCREEN_TOP_N`, `SENTIMENT_MODEL`, `EMBED_MODEL`, `MAX_FILING_CHARS`, `WATCHLIST` | Pipeline tuning |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Weekly digest and alerts |
| `QUANT_API_TOKEN` | Quant API: empty = this machine only |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_BEHIND_PROXY` | Website (local dashboard) |
| `APP_DATA_PASSWORD` | Encrypts the app's data file (`site-data/data.json`) |
| `CONTACT_LINKEDIN_URL`, `CONTACT_GITHUB_URL` | Contact links on the website |

The app's build settings (`DATA_URL`, `BENCHMARK`, `LINKEDIN_URL`, `GITHUB_URL`) go in `app/config.json`
locally; CI writes them itself. They're all public; the app holds no keys or passwords.

### Repository layout

```
TI-Agent/
├── common/          config, HTTP, database store (store.py), schema setup (db_init.py), logging
├── db/              schema.sql: tables, indexes, search functions (M3)
├── ingestion/       M1 sources + refresh.py (incremental updates)
├── processing/      M2 chunking, embeddings, FinBERT
├── quant/           M4 features, weekly screen, FastAPI app
├── retrieval/       M5 hybrid search + evaluation queries
├── agent/           M6 tools, agent loop, schema checks, prompts
├── orchestration/   M8 weekly_run.py, screen_run.py, retention.py
├── delivery/        M9 Telegram
├── web/             M9 Django dashboard (local only)
├── app/             M9 Flutter app
├── scripts/         setup, model build, task registration, database start-up, smoke test
├── docs/            progress, architecture, security, references
├── tests/           offline tests (in-memory fakes)
├── docker-compose.yml               local PostgreSQL + pgvector
├── site-data/      the app's encrypted data file (data.json): push it to publish
├── run_daily.cmd · run_screen.cmd · run_weekly.cmd
└── watchlist.txt                    tickers used before the first screen
```

### Guardrails

- **No lookahead:** every read is limited to data published before the as-of date.
- **Code-enforced agent rules:** the agent can't trade; its only write is a validated suggestion. Citations
  must come from the same run, and numbers must match tool outputs.
- **Database:** listens on 127.0.0.1 only; nothing outside the laptop can reach it.
- **Invite-only:** the dashboard and app have no public sign-up. Publishing investment recommendations publicly
  may fall under EU market rules (MAR).

### Documentation

- [docs/progress.md](docs/progress.md): detailed status, run history, known limitations
- [docs/architecture.md](docs/architecture.md): how each module works and why, with citations
- [docs/security.md](docs/security.md): threat model and security review
- [docs/references.md](docs/references.md) ([BibTeX](docs/references.bib)): the 22 papers the design builds on
- [app/README.md](app/README.md): Flutter app development

### Key references

- Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, 2020. [arXiv:2005.11401](https://arxiv.org/abs/2005.11401)
- Glasserman & Lin, *Assessing Look-Ahead Bias in Stock Return Predictions Generated By GPT Sentiment Analysis*, 2023. [arXiv:2309.17322](https://arxiv.org/abs/2309.17322)
- Araci, *FinBERT: Financial Sentiment Analysis with Pre-trained Language Models*, 2019. [arXiv:1908.10063](https://arxiv.org/abs/1908.10063)
- Reimers & Gurevych, *Sentence-BERT*, 2019. [arXiv:1908.10084](https://arxiv.org/abs/1908.10084)
- Thakur et al., *BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of Information Retrieval Models*, 2021. [arXiv:2104.08663](https://arxiv.org/abs/2104.08663)
- Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models*, 2022. [arXiv:2210.03629](https://arxiv.org/abs/2210.03629)
- Farhi, Goldstone & Gutmann, *A Quantum Approximate Optimization Algorithm*, 2014. [arXiv:1411.4028](https://arxiv.org/abs/1411.4028)

## License

MIT License
