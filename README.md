# TI Agent — Trading Intelligence

An agentic, retrieval-augmented AI that screens the whole **S&P 500** every week and produces **medium-term (1–3 months)** and **long-term (6–24 months)** trading suggestions for the **top 20** picks, grounded in news, SEC filings, macro data and price history — built entirely on **free tools**, with a **quantum computing** research layer planned for portfolio optimization.

> **Disclaimer:** TI Agent is a research and learning project. Its output is not financial advice. It never places trades. Use at your own risk.

---

## Status (2026-11-11)

| Part | State |
|---|---|
| P1 Foundations: daily ingestion and processing | Built. 2-year backfill loaded with 0 errors. Gate: 7 clean daily runs, earliest **2026-11-19** |
| P2 Knowledge: quant engine, hybrid retrieval | Built. **Gate passed** (10/10 test queries relevant with rerank) |
| S&P 500 screen: momentum among quality companies, top 20 | Built. Runs in GitHub Actions on Fridays; the daily ingest and the weekly agent then work on the picks |
| P3 Agent: weekly LLM run | Built. **1 of 4** clean weekly runs done (5 tickers, 10 cited suggestions) |
| App (Flutter: web, Android, iOS) | Code written. GitHub Actions will compile, test and publish the web version to GitHub Pages on the next push |
| Django dashboard | Built. Local tool for the owner (pipeline status, computed features) |
| P5 Quantum + evaluation | Not started |

96 offline tests. Details: [docs/progress.md](docs/progress.md). Security review: [docs/security.md](docs/security.md).

## What it does

1. **Screens** all ~503 S&P 500 stocks weekly: momentum (12-1 month, vs S&P 500) among profitable, cash-generating companies, and keeps the top 20.
2. **Collects** news, filings, macro series and prices for the picks every weekday.
3. **Indexes** text into a vector store, tagged by ticker, date and source.
4. **Reasons** with a local LLM agent that calls tools to gather evidence for each ticker.
5. **Suggests** a structured, cited view per ticker: stance, thesis, risks, confidence.
6. **Optimizes** a portfolio from the suggestions, benchmarking quantum (QAOA) against classical solvers *(planned, P5)*.
7. **Delivers** results through one Flutter app (web, Android, iOS) and Telegram.
8. **Evaluates** every past suggestion against real returns and a benchmark *(planned, P5)*.

## Architecture

```
GitHub Actions (cloud, Fridays 23:30 UTC): S&P 500 screen
  Wikipedia constituents · yfinance prices · SEC XBRL fundamentals (all ~503)
  → momentum among quality companies → top 20 → Supabase "screens"
  → backfill news + filings for new picks

GitHub Actions (cloud, weekdays 22:30 UTC): picks only
  Finnhub · SEC EDGAR · FRED · yfinance
  → clean, chunk, embed (MiniLM), score news (FinBERT)
  → Supabase (Postgres + pgvector)

Laptop (weekly, GPU)
  AI Finance Agent (Ollama · Qwen3.5 4B)
    tools: search_knowledge · get_features · get_prices · get_macro · save_suggestion
  → Supabase "suggestions"

Delivery
  Flutter app: web (GitHub Pages) · Android · iOS
    Supabase Auth + anon key, row-level security, invite-only
  Telegram bot
  Django dashboard (local, owner only)

Planned (P5)
  optimize_portfolio tool (classical vs QAOA) → "portfolio_runs"
  monthly evaluation → "performance"
```

Supabase is the single hand-off point: every module reads from and writes to it, so each part can be developed and replaced independently.

## Modules

| # | Module | Job | Runs on | State |
|---|---|---|---|---|
| M1 | Ingestion | Pull news, filings, XBRL fundamentals, prices, macro | GitHub Actions (daily) | Built |
| M2 | Processing + embedding | Clean, chunk, tag, embed, sentiment | GitHub Actions (daily) | Built |
| M3 | Knowledge store | Data, vectors, auth, row-level security | Supabase (cloud) | Built |
| M4 | Quant engine | Indicators, ratios, sentiment aggregates; weekly S&P 500 screen | Laptop (FastAPI) + GitHub Actions (screen) | Built |
| M5 | Retrieval | Hybrid search, date-filtered, rerank | Laptop | Built |
| M6 | AI Finance Agent | Tool-calling LLM that writes suggestions | Laptop GPU (Ollama) | Built |
| M7 | Portfolio + quantum | Classical vs QAOA allocation, quantum-kernel regime classifier | Laptop CPU (simulators) | Planned |
| M8 | Orchestration | Weekly run, retries, alerts | Laptop (Task Scheduler) | Built |
| M9 | Delivery | Website, app, Telegram | Laptop / cloud / phone | Website built; app written; Telegram not configured |
| M10 | Evaluation | Score suggestions vs returns | GitHub Actions (monthly) | Planned |

## Tech stack (all free)

| Layer | Tools |
|---|---|
| Data | Finnhub (free tier), SEC EDGAR, FRED, yfinance |
| Storage | Supabase free tier (Postgres, pgvector, auth) |
| Embeddings and NLP | sentence-transformers `all-MiniLM-L6-v2`, cross-encoder `ms-marco-MiniLM-L-6-v2`, FinBERT |
| LLM | Ollama + Qwen3.5 4B (Q4, text-only build, tool calling + thinking) |
| Backend | Python, FastAPI, pandas, pydantic |
| Website | Django 5.2, Chart.js |
| App | Flutter, supabase_flutter, fl_chart |
| Quantum (planned) | Qiskit, PennyLane (simulators) |
| Orchestration | GitHub Actions, Windows Task Scheduler |
| Notifications | Telegram bot |

## Suggestion format

Every suggestion is validated JSON. `ticker` and `as_of` are set by code, never by the model; every
`sources` entry must have come from a search in the same run, and every number must match a tool output.

```json
{
  "ticker": "AAPL",
  "horizon": "long",
  "stance": "bullish",
  "thesis": "Short explanation grounded in cited sources.",
  "risks": ["Risk one", "Risk two"],
  "sources": ["chunk_1842", "chunk_1907"],
  "confidence": 0.62,
  "as_of": "2026-11-11"
}
```

## Repository structure

```
TI-Agent/
├── .github/workflows/
│   ├── ingest.yml          # M1 + M2 for the picks, weekdays
│   ├── screen.yml          # S&P 500 screen, Fridays
│   └── app.yml             # Flutter: test, web (GitHub Pages), APK
├── common/                 # config, HTTP, Supabase store, logging
├── ingestion/              # M1
├── processing/             # M2
├── db/                     # M3: schema.sql, rls.sql
├── quant/                  # M4: features + FastAPI app
├── retrieval/              # M5: hybrid search + evaluation queries
├── agent/                  # M6: tools, agent loop, schema checks, prompts/
├── orchestration/          # M8: weekly_run.py, screen_run.py
├── delivery/               # M9: Telegram
├── web/                    # M9: Django website (dashboard/, tiweb/)
├── app/                    # M9: Flutter app
├── scripts/                # setup, model build, task registration, smoke test
├── docs/                   # progress, architecture, security, references
├── tests/
├── watchlist.txt
├── .env.example
└── README.md
```

Planned for P5: `portfolio/` (M7) and `evaluation/` + `evaluate.yml` (M10).

## Requirements

- Windows/Linux/macOS, Python 3.11+
- NVIDIA GPU with ≥ 6 GB VRAM for `qwen3.5:4b` (or `qwen3.5:2b` on smaller GPUs / CPU; `qwen3.5:9b` with ≥ 10 GB)
- About 5 GB of free commit memory (RAM + page file) during the weekly run
- Free accounts: GitHub, Supabase, Finnhub, FRED, Telegram (bot via BotFather)
- Flutter SDK (only for the app)

## Quickstart

```powershell
# 1. Clone and install
git clone https://github.com/nsskn982/TI-Agent.git
cd TI-Agent
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure secrets
copy .env.example .env          # fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, FINNHUB_API_KEY, ...

# 3. Create the database: run db/schema.sql, then db/rls.sql, in the Supabase SQL editor
#    (both are safe to re-run; re-run them after pulling changes to db/)

# 4. Build the local model
.\scripts\create_model.ps1      # pulls qwen3.5:4b, builds the text-only trading-analyst (fits 6 GB)

# 5. Load data. Before the first S&P 500 screen, watchlist.txt sets the tickers; afterwards the
#    latest top-20 picks do (--tickers always overrides).
python -m orchestration.screen_run    # S&P 500 screen: ~45 min the first time (also runs Fridays in Actions)
python -m ingestion.run --days 730    # first run: ~2-year backfill
python -m processing.run              # chunk, embed, score news
python -m pytest -q                   # offline tests, no keys needed

# 6. Check retrieval (Phase 2 gate)
python -m retrieval.evaluate --rerank
```

Weekly agent run (Phase 3): double-click **`run_weekly.cmd`** in the repo folder. It starts Ollama if
needed, runs this week's S&P 500 picks (about 20 min), and logs to `logs\weekly_run.log`. It also takes
options, e.g. `run_weekly.cmd --tickers AAPL --no-telegram`. Or, from a terminal:

```powershell
python -m orchestration.weekly_run --tickers AAPL --no-telegram   # smoke test, one ticker
python -m orchestration.weekly_run                                # full watchlist
.\scripts\register_weekly_task.ps1                                # every Saturday 09:00
```

Close memory-heavy apps (browsers) during the run: the model needs about 4.6 GB of Windows commit memory.

Add the same secrets to **GitHub → Settings → Secrets and variables → Actions** so the daily workflow can run.

### Windows setup script

From PowerShell at the repository root, run:

```powershell
.\scripts\setup.ps1
```

The script creates `.venv`, installs `requirements.txt`, creates `.env` from `.env.example` without overwriting an existing file, configures the recommended Ollama user settings, and builds the model. Use `-OllamaModel qwen3.5:2b` for a smaller GPU or CPU, `-SkipOllama` to configure Python only, or `-SkipPython` to configure Ollama only.

### Recommended Ollama settings (6 GB VRAM)

```powershell
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
setx OLLAMA_CONTEXT_LENGTH 16384
```

Restart Ollama afterwards and check `ollama ps` shows `100% GPU`. Leave `OLLAMA_HOST` at its default
(`127.0.0.1`); `0.0.0.0` would expose the model to everyone on your network.

## Environment variables

Set in `.env` (never commit it). The app's settings go in `app/config.json` instead.

| Variable | Used by |
|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Ingestion, processing, agent, website (server-side only) |
| `FINNHUB_API_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT` | Ingestion (EDGAR requires a contact email in the user agent) |
| `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_THINK` | Agent (defaults: `http://localhost:11434`, `trading-analyst`, `16384`, `true`) |
| `BENCHMARK` | Quant engine (default `SPY`) |
| `SCREEN_TOP_N` | S&P 500 screen: how many picks get the full pipeline (default `20`) |
| `SENTIMENT_MODEL` | Processing (default FinBERT) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Weekly digest and alerts |
| `QUANT_API_TOKEN` | Local API: empty = answer this machine only |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_BEHIND_PROXY` | Website |
| `CONTACT_LINKEDIN_URL`, `CONTACT_GITHUB_URL` | Website Contact links (empty hides the icon) |

`app/config.json` (git-ignored) holds `SUPABASE_URL`, the **anon** key `SUPABASE_ANON_KEY`, `BENCHMARK`,
`LINKEDIN_URL` and `GITHUB_URL`. Never put the service key in the app.

## Roadmap

| Phase | Scope | Gate | Status |
|---|---|---|---|
| P1 Foundations | Supabase schema, daily ingestion | 7 days of data without errors | In progress (earliest pass 2026-11-19) |
| P2 Knowledge | Embeddings, quant engine, retrieval | Relevant chunks on 10 test queries | **Passed** |
| P3 Agent | AI Finance Agent, weekly run, Telegram | 4 weekly runs of valid, cited JSON | 1 / 4 (from the next run: top 20 S&P 500 picks, ~20 min) |
| P4 App | Flutter app (web, Android, iOS) | Invite-only testers for 2 weeks | App written; web publish via GitHub Pages set up |
| P5 Quantum + eval | QAOA, quantum kernel, scoring | Quantum vs classical benchmark report | Not started |

## Dashboard (Django, local)

An owner's research dashboard in [web/](web/), run on your own machine. It reads from Supabase server-side (the service key
never reaches the browser), and its own SQLite database holds only the logins.

```powershell
python web/manage.py migrate                  # once: creates web/db.sqlite3 for users and sessions
python web/manage.py invite alice --admin     # prints a one-time password; there is no public sign-up
python web/manage.py runserver                # http://127.0.0.1:8000  (needs DJANGO_DEBUG=true in .env)
```

| Page | Shows |
|---|---|
| `/` | A scroll story: an intro with this week's numbers, an at-a-glance grid, then one full-screen scene per ticker where its two views slide in as you scroll (marked **New** or **Changed from …** against the previous run), ending with a contact section |
| `/t/<ticker>/` | 12-month price chart against the benchmark, the computed features the agent saw, suggestion history |
| `/c/<chunk_id>/` | The exact passage a suggestion cites, with a link to the original SEC filing or article |
| `/status/` | Roadmap gates, agent runs, ingestion and processing runs |

The **Contact** tab in the header (and the closing scene) links to LinkedIn and GitHub.

Security:

- **Logins:** throttled, and sessions last 12 hours.
- **Scripts:** a strict Content-Security-Policy lets only the site's own scripts run.
The dashboard runs on your own machine and isn't hosted; the Flutter app is what other people use.

## App (Flutter): web, Android, iOS

[app/](app/) is the client everyone else uses: sign-in, the same scroll story of this week's suggestions,
ticker charts, cited passages and the Contact links. One codebase for every platform:

| Platform | Build | Delivery |
|---|---|---|
| Web | GitHub Actions ([app.yml](.github/workflows/app.yml)), on every push to `main` | GitHub Pages: `https://nsskn982.github.io/TI-Agent/` |
| Android | `flutter build apk` | APK sent to invited testers |
| iOS | `flutter build ipa` on a Mac | TestFlight (Apple Developer account) |

It reads Supabase directly with the anon key and Supabase Auth, under the policies in
[db/rls.sql](db/rls.sql). It has no server of its own, so there's nothing to host except static files. The
app refuses to start with a service key, and the workflow refuses to publish one. Setup:
[app/README.md](app/README.md). **Turn off public sign-ups in Supabase first.**

## Quant + retrieval API (M4, M5)

`uvicorn quant.api:app --port 8000` (docs at <http://localhost:8000/docs>). It answers requests from this
machine only, unless `QUANT_API_TOKEN` is set; then every request needs `Authorization: Bearer <token>`.

| Route | Returns |
|---|---|
| `GET /features/{ticker}?as_of=` | Technicals (returns, SMA, RSI, MACD, vol, drawdown, beta and relative strength vs `BENCHMARK`), point-in-time TTM fundamentals from SEC XBRL (growth, margins, P/E, FCF yield, D/E), FinBERT news-sentiment aggregates |
| `GET /prices/{ticker}?as_of=&days=` | Daily bars |
| `GET /macro?as_of=` | FRED snapshot with release lags applied (e.g. CPI counts ~45 days after its observation date) |
| `GET /search?q=&ticker=&source=&as_of=&k=&rerank=` | Hybrid vector + keyword search (RRF), optional cross-encoder rerank, max 2 chunks per document, each hit with a `chunk_<id>` citation |

Every route only sees data from strictly before `as_of`: prices before that day, filings and XBRL facts
filed before it, news published before it.

## Evaluation (planned, P5)

- **Hit rate** at 1, 3 and 12 months
- **Excess return** vs a benchmark index
- **Calibration**: higher confidence should mean higher hit rate
- **Citation faithfulness**: claims match their cited sources
- **Quantum benchmark**: QAOA vs classical objective value and runtime

## Guardrails

- Retrieval is always filtered to data published before the as-of date (no lookahead).
- The agent has read-only tools plus one write tool (`save_suggestion`); it cannot trade.
- Citations must come from the same run; numbers must match tool outputs; theses must be in English.
- Agent runs are capped at a fixed number of tool steps and every tool call is logged.
- The website and app are private and invite-only; publishing investment recommendations publicly may fall under EU market rules (MAR).

## Documentation

- [docs/progress.md](docs/progress.md): current status of every phase, the website and the app; next steps; known limitations
- [docs/architecture.md](docs/architecture.md): how each module works and why, with citations
- [docs/security.md](docs/security.md): threat model, security review findings and fixes, setup steps you must do
- [docs/references.md](docs/references.md) ([BibTeX](docs/references.bib)): research the design builds on
- [app/README.md](app/README.md): Flutter app setup

## Key references

The design builds on these papers; the full list of 22 arXiv papers is in [docs/references.md](docs/references.md).

- Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, 2020. [arXiv:2005.11401](https://arxiv.org/abs/2005.11401)
- Glasserman & Lin, *Assessing Look-Ahead Bias in Stock Return Predictions Generated By GPT Sentiment Analysis*, 2023. [arXiv:2309.17322](https://arxiv.org/abs/2309.17322)
- Araci, *FinBERT: Financial Sentiment Analysis with Pre-trained Language Models*, 2019. [arXiv:1908.10063](https://arxiv.org/abs/1908.10063)
- Reimers & Gurevych, *Sentence-BERT*, 2019. [arXiv:1908.10084](https://arxiv.org/abs/1908.10084)
- Thakur et al., *BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of Information Retrieval Models*, 2021. [arXiv:2104.08663](https://arxiv.org/abs/2104.08663)
- Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models*, 2022. [arXiv:2210.03629](https://arxiv.org/abs/2210.03629)
- Farhi, Goldstone & Gutmann, *A Quantum Approximate Optimization Algorithm*, 2014. [arXiv:1411.4028](https://arxiv.org/abs/1411.4028)

## License

MIT License
