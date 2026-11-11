"""The agent's tools: four read-only tools and one write tool (save_suggestion).

The model never chooses the as-of date: every tool is bound to `ToolContext.as_of`,
so it cannot ask for data from the future. `save_suggestion` is the only write,
and it rejects anything ungrounded.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from pydantic import ValidationError

from agent.schema import Suggestion, source_numbers, unsupported_numbers
from quant import features

MAX_RESULT_CHARS = 3500
SNIPPET_CHARS = 600

TOOL_SPECS: list[dict] = [
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": "Search news and SEC filings published before the as-of date. Returns passages "
                       "with ids like chunk_123. Only ids returned here may be cited.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to look for, in plain English"},
            "source": {"type": "string", "enum": ["news", "filing"], "description": "Optional filter"},
            "ticker": {"type": "string", "description": "Defaults to the ticker being analysed"},
            "k": {"type": "integer", "description": "Number of passages, 1-6 (default 5)"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "get_features",
        "description": "Computed technicals, TTM fundamentals and news sentiment for a ticker. Ratios are "
                       "fractions (0.151 = 15.1%). Fields: ret_1m/3m/6m/12m = price return over that window; "
                       "pct_vs_sma_50/200 = distance from that moving average; pct_from_52w_high/low = distance "
                       "from the 52-week extreme; vol_20d = annualised volatility; rel_strength_3m = 3-month "
                       "return minus the benchmark's; revenue_growth_yoy = TTM vs a year earlier; fcf_ttm = free "
                       "cash flow in dollars; fcf_yield = fcf_ttm / market_cap; sentiment mean_* = FinBERT score "
                       "from -1 to 1. Always name the field you quote correctly.",
        "parameters": {"type": "object", "properties": {
            "ticker": {"type": "string", "description": "Defaults to the ticker being analysed"},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_prices",
        "description": "Weekly closing prices for a ticker (most recent last).",
        "parameters": {"type": "object", "properties": {
            "ticker": {"type": "string"},
            "weeks": {"type": "integer", "description": "1-52 (default 26)"},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_macro",
        "description": "Latest macro series (rates, curve, CPI, unemployment, VIX, credit spreads).",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "save_suggestion",
        "description": "Save one suggestion for the ticker being analysed. Call once per horizon.",
        "parameters": {"type": "object", "properties": {
            "horizon": {"type": "string", "enum": ["medium", "long"],
                        "description": "medium = 1-3 months, long = 6-24 months"},
            "stance": {"type": "string", "enum": ["bullish", "neutral", "bearish"],
                       "description": "Expected performance relative to the benchmark"},
            "thesis": {"type": "string", "description": "2-4 sentences: the call and the main reason"},
            "bull_case": {"type": "string", "description": "2-3 sentences: what has to go right, with evidence"},
            "bear_case": {"type": "string", "description": "2-3 sentences: what could go wrong, with evidence"},
            "catalysts": {"type": "array", "items": {"type": "string"},
                          "description": "1-4 dated or specific events that could move the stock in this horizon "
                                         "(earnings date, product launch, rate decision, regulation)"},
            "valuation": {"type": "string",
                          "description": "1-2 sentences on valuation using get_features numbers "
                                         "(pe_ttm, fcf_yield, growth); say 'not available' if missing"},
            "risks": {"type": "array", "items": {"type": "string"}, "description": "1-5 key risks"},
            "sources": {"type": "array", "items": {"type": "string"},
                        "description": "chunk ids from search_knowledge supporting the thesis"},
            "confidence": {"type": "number", "description": "0-1; 0.5 means no edge"},
        }, "required": ["horizon", "stance", "thesis", "bull_case", "bear_case", "catalysts", "valuation",
                        "risks", "sources", "confidence"]},
    }},
]


def _compact(obj: Any) -> Any:
    """Drop nulls so tool results spend the context window on information."""
    if isinstance(obj, dict):
        return {k: _compact(v) for k, v in obj.items() if v is not None and v != {}}
    if isinstance(obj, list):
        return [_compact(v) for v in obj]
    return obj


def _dump(obj: Any) -> str:
    text = json.dumps(_compact(obj), separators=(",", ":"), default=str)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "...[truncated]"


@dataclass
class ToolContext:
    store: Any
    retriever: Any
    ticker: str
    as_of: date
    run_id: int | None = None
    model: str | None = None
    allowed_tickers: set[str] | None = None
    on_call: Callable[[dict], None] | None = None
    rerank: bool = True
    seen_citations: set[str] = field(default_factory=set)
    results_text: list[str] = field(default_factory=list)
    saved: dict[str, dict] = field(default_factory=dict)
    step: int = 0

    # ------------------------------------------------------------ dispatch
    def execute(self, name: str, args: dict | None) -> str:
        args = args or {}
        start = time.perf_counter()
        fn = getattr(self, f"_tool_{name}", None)
        if fn is None:
            result = f"ERROR: unknown tool {name!r}. Available: {[t['function']['name'] for t in TOOL_SPECS]}"
        else:
            try:
                result = fn(**args)
            except TypeError as exc:
                result = f"ERROR: bad arguments for {name}: {exc}"
            except Exception as exc:  # tools must never crash the loop
                result = f"ERROR: {name} failed: {type(exc).__name__}: {exc}"
        if name != "save_suggestion" and not result.startswith("ERROR"):
            self.results_text.append(result)
        if self.on_call:
            self.on_call({
                "run_id": self.run_id, "ticker": self.ticker, "step": self.step, "tool": name,
                "arguments": args, "result_summary": result[:500],
                "duration_ms": int((time.perf_counter() - start) * 1000),
            })
        return result

    def _ticker(self, ticker: str | None) -> str:
        t = (ticker or self.ticker).upper()
        if self.allowed_tickers is not None and t not in self.allowed_tickers:
            raise ValueError(f"{t} is not on the watchlist")
        return t

    # ------------------------------------------------------------ read-only tools
    def _tool_search_knowledge(self, query: str, source: str | None = None, ticker: str | None = None,
                               k: int = 5) -> str:
        k = max(1, min(int(k), 6))
        # Rerank on by default: in the Phase 2 evaluation it lifted on-topic top results
        # from about 7/10 to 10/10 for ~0.5 s per query.
        hits = self.retriever.search(query, self.as_of, k=k, ticker=self._ticker(ticker), source=source,
                                     rerank=self.rerank)
        if not hits:
            return "No passages found. Try a broader query or a different source."
        out = []
        for h in hits:
            self.seen_citations.add(h.citation)
            out.append({"id": h.citation, "date": h.published_at[:10], "type": h.doc_type or h.source,
                        "title": h.title, "text": " ".join(h.content.split())[:SNIPPET_CHARS]})
        return _dump(out)

    def _tool_get_features(self, ticker: str | None = None) -> str:
        f = features.compute_features(self.store, self._ticker(ticker), self.as_of)
        if not f.get("price"):
            return f"ERROR: no price history for {f['ticker']}"
        return _dump(f)

    def _tool_get_prices(self, ticker: str | None = None, weeks: int = 26) -> str:
        weeks = max(1, min(int(weeks), 52))
        t = self._ticker(ticker)
        close = features.close_series(features.get_prices(self.store, t, self.as_of, days=weeks * 7 + 14))
        if close.empty:
            return f"ERROR: no price history for {t}"
        # Last actual trading day of each week (resample would label a partial week
        # with the coming Friday, i.e. a date after as_of).
        weekly = close.groupby(close.index.to_period("W-FRI")).tail(1).iloc[-weeks:]
        return _dump({"ticker": t, "weekly_close": {d.date().isoformat(): round(float(v), 2)
                                                     for d, v in weekly.items()}})

    def _tool_get_macro(self) -> str:
        return _dump(features.compute_macro(self.store, self.as_of))

    # ------------------------------------------------------------ the one write tool
    def _tool_save_suggestion(self, **kwargs) -> str:
        # The model may echo these back; the code-supplied values always win.
        kwargs.pop("ticker", None)
        kwargs.pop("as_of", None)
        try:
            s = Suggestion(ticker=self.ticker, as_of=self.as_of, **kwargs)
        except ValidationError as exc:
            errs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return f"ERROR: invalid suggestion ({errs}). Fix it and call save_suggestion again."

        problems = []
        unseen = [c for c in s.sources if c not in self.seen_citations]
        if unseen:
            problems.append(f"sources {unseen} were not returned by search_knowledge in this session")
        nums = unsupported_numbers(s.text_for_checks(), source_numbers(self.results_text))
        if nums:
            problems.append(f"numbers {nums} do not match any tool output; use only tool values (e.g. 0.151 -> "
                            f"15.1%, 478834000000 -> $478.8B) or describe them in words")
        if problems:
            return "ERROR: " + " | ".join(problems) + ". Fix it and call save_suggestion again."

        row = s.to_row(self.run_id, self.model)
        self.store.upsert_suggestion(row)
        self.saved[s.horizon] = row
        missing = self.missing_horizons()
        return f"Saved {s.horizon} suggestion." + (f" Still needed: {missing}." if missing else " All done.")

    def missing_horizons(self) -> list[str]:
        return [h for h in ("medium", "long") if h not in self.saved]
