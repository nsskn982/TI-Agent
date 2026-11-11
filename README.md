# TI-Agent
Disclaimer: TI Agent is a research and learning project. Its output is not financial advice. It never places trades. Use at your own risk.
# TI Agent — Trading Intelligence

An agentic, retrieval-augmented AI that produces **medium-term (1–3 months)** and **long-term (6–24 months)** trading suggestions for a watchlist, grounded in news, SEC filings, macro data and price history — built entirely on **free tools**, with a **quantum computing** research layer for portfolio optimization.

> **Disclaimer:** TI Agent is a research and learning project. Its output is not financial advice. It never places trades. Use at your own risk.

---

## What it does

1. **Collects** news, filings, macro series and prices every day.
2. **Indexes** text into a vector store, tagged by ticker, date and source.
3. **Reasons** with a local LLM agent that calls tools to gather evidence for each ticker.
4. **Suggests** a structured, cited view per ticker: stance, thesis, risks, confidence.
5. **Optimizes** a portfolio from the suggestions, benchmarking quantum (QAOA) against classical solvers.
6. **Delivers** results to a Flutter app, a website and Telegram.
7. **Evaluates** every past suggestion against real returns and a benchmark.

## Architecture

```
GitHub Actions (cloud, daily)
  Finnhub · SEC EDGAR · FRED · yfinance
  → clean, chunk, embed (MiniLM)
  → Supabase (Postgres + pgvector)

Laptop (weekly, GPU)
  AI Finance Agent (Ollama · Qwen2.5 7B)
    tools: search_knowledge · get_features · get_prices
           get_macro · optimize_portfolio · save_suggestion
  → Supabase "suggestions" + "portfolio_runs"

Delivery
  Supabase realtime → Flutter app + web (GitHub Pages)
  Firebase Cloud Messaging · Telegram bot

GitHub Actions (cloud, monthly)
  → score past suggestions → Supabase "performance"
```

Supabase is the single hand-off point: every module reads from and writes to it, so each part can be developed and replaced independently.

## Modules

| # | Module | Job | Runs on |
|---|---|---|---|
| M1 | Ingestion | Pull news, filings, prices, macro | GitHub Actions (daily) |
| M2 | Processing + embedding | Clean, chunk, tag, embed | GitHub Actions (daily) |
| M3 | Knowledge store | Data, vectors, auth, realtime | Supabase (cloud) |
| M4 | Quant engine | Indicators, ratios, sentiment aggregates | Laptop (FastAPI) |
| M5 | Retrieval | Hybrid search, date-filtered, optional rerank | Laptop |
| M6 | AI Finance Agent | Tool-calling LLM that writes suggestions | Laptop GPU (Ollama) |
| M7 | Portfolio + quantum | Classical vs QAOA allocation, quantum-kernel regime classifier | Laptop CPU (simulators) |
| M8 | Orchestration | Weekly run, retries, alerts | Laptop (Task Scheduler → n8n) |
| M9 | Delivery | App, website, push, Telegram | Cloud + phone |
| M10 | Evaluation | Score suggestions vs returns | GitHub Actions (monthly) |

## Tech stack (all free)

| Layer | Tools |
|---|---|
| Data | Finnhub (free tier), SEC EDGAR, FRED, yfinance |
| Storage | Supabase free tier (Postgres, pgvector, auth, realtime) |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` |
| LLM | Ollama + Qwen2.5 7B Instruct (Q4) |
| Backend | Python, FastAPI, pandas, `ta`, pydantic |
| Quantum | Qiskit, PennyLane (simulators; IBM Quantum free plan optional) |
| Classical baseline | PyPortfolioOpt |
| Orchestration | GitHub Actions, Windows Task Scheduler, n8n (self-hosted, v2) |
| Frontend | Flutter (mobile + web), GitHub Pages |
| Notifications | Firebase Cloud Messaging, Telegram bot |

## Suggestion format

Every suggestion is validated JSON:

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
ti-agent/
├── .github/workflows/
│   ├── ingest.yml          # M1 + M2, daily
│   └── evaluate.yml        # M10, monthly
├── ingestion/              # M1
├── processing/             # M2
├── db/                     # M3: schema.sql, rls.sql
├── quant/                  # M4: FastAPI app
├── retrieval/              # M5
├── agent/                  # M6: tools.py, agent.py, prompts/, Modelfile
├── portfolio/              # M7: classical.py, qaoa.py, qkernel.py
├── orchestration/          # M8: weekly_run.py, n8n/
├── evaluation/             # M10
├── app/                    # M9: Flutter project
├── tests/
├── .env.example
└── README.md
```

## Requirements

- Windows/Linux/macOS, Python 3.11+
- NVIDIA GPU with ≥ 6 GB VRAM for the 7B model (or use `qwen2.5:3b` on smaller GPUs / CPU)
- Free accounts: GitHub, Supabase, Finnhub, Firebase, Telegram (bot via BotFather)
- Flutter SDK (for the app)

## Quickstart

```bash
# 1. Clone and install
git clone https://github.com/<you>/ti-agent.git
cd ti-agent
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

# 2. Configure secrets
cp .env.example .env          # fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, FINNHUB_API_KEY, ...

# 3. Create the database
#    Run db/schema.sql and db/rls.sql in the Supabase SQL editor

# 4. Set up the local model
ollama pull qwen2.5:7b
ollama create trading-analyst -f agent/Modelfile

# 5. Run once by hand (watchlist lives in watchlist.txt; --tickers overrides it)
python -m ingestion.run --tickers AAPL MSFT --days 730   # first run: ~2-year backfill
python -m processing.run
python -m pytest -q                                      # offline tests, no keys needed
python -m orchestration.weekly_run
```

Add the same secrets to **GitHub → Settings → Secrets and variables → Actions** so the daily and monthly workflows can run.

### Windows setup script

From PowerShell at the repository root, run:

```powershell
.\scripts\setup.ps1
```

The script creates `.venv`, installs `requirements.txt` when it is present, creates `.env` from `.env.example` without overwriting an existing file, configures the recommended Ollama user settings, and pulls the selected model. Use `-OllamaModel qwen2.5:3b` for a smaller GPU or CPU, `-SkipOllama` to configure Python only, or `-SkipPython` to configure Ollama only.

### Recommended Ollama settings (6 GB VRAM)

```powershell
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
setx OLLAMA_CONTEXT_LENGTH 8192
setx OLLAMA_KEEP_ALIVE 5m
setx OLLAMA_HOST 0.0.0.0:11434
```

Restart Ollama afterwards and check `ollama ps` shows `100% GPU`.

## Environment variables

| Variable | Used by |
|---|---|
| `SUPABASE_URL` | All modules |
| `SUPABASE_SERVICE_KEY` | Writers (ingestion, agent, evaluation) |
| `SUPABASE_ANON_KEY` | Flutter app |
| `FINNHUB_API_KEY` | Ingestion |
| `FRED_API_KEY` | Ingestion |
| `SEC_USER_AGENT` | Ingestion (EDGAR requires a contact email) |
| `OLLAMA_URL` | Agent (default `http://localhost:11434`) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Delivery |

Never commit `.env`.

## Roadmap

| Phase | Weeks | Scope | Gate |
|---|---|---|---|
| P1 Foundations | 1–2 | Supabase schema, daily ingestion | 7 days of data without errors |
| P2 Knowledge | 3–4 | Embeddings, quant engine, retrieval | Relevant chunks on 10 test queries |
| P3 Agent | 5–6 | AI Finance Agent, weekly run, Telegram | 4 weekly runs of valid, cited JSON |
| P4 App | 7–9 | Flutter app + web, push | Invite-only testers for 2 weeks |
| P5 Quantum + eval | 10–12 | QAOA, quantum kernel, scoring, n8n | Quantum vs classical benchmark report |

## Evaluation

- **Hit rate** at 1, 3 and 12 months
- **Excess return** vs a benchmark index
- **Calibration**: higher confidence should mean higher hit rate
- **Citation faithfulness**: claims match their cited sources
- **Quantum benchmark**: QAOA vs classical objective value and runtime

## Guardrails

- Retrieval is always filtered to data published before the as-of date (no lookahead).
- The agent has read-only tools plus one write tool (`save_suggestion`); it cannot trade.
- Agent runs are capped at a fixed number of tool steps and every tool call is logged.
- Numbers come from code, never from the LLM.
- The app stays private or invite-only; publishing investment recommendations publicly may fall under EU market rules (MAR).

## License

MIT License