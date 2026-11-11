import json
import re
from datetime import date

import pandas as pd
import pytest

from agent import agent as agent_mod
from agent.agent import fit_context, run_ticker
from agent.llm import LLMError, OllamaClient, parse_text_tool_calls
from agent.schema import source_numbers, unsupported_numbers
from agent.tools import TOOL_SPECS, ToolContext
from delivery import telegram
from orchestration.weekly_run import run as weekly_run
from processing.run import process
from retrieval.search import Retriever
from tests.fakes import FakeEmbedder, FakeReranker, FakeStore

AS_OF = date(2026, 11, 11)


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def store():
    s = FakeStore()
    s.insert_documents([
        {"ticker": t, "source": "news", "source_id": f"{t}-1", "doc_type": "Reuters",
         "title": f"{t} demand strong", "url": "u", "published_at": "2026-11-02T12:00:00+00:00",
         "body": f"{t} reported demand above expectations and raised guidance."}
        for t in ("AAPL", "MSFT")
    ])
    process(s, FakeEmbedder())
    for i, d in enumerate(pd.bdate_range("2025-06-01", "2026-11-10")):
        for t, px in (("AAPL", 100 + i * 0.1), ("MSFT", 300 + i * 0.2), ("SPY", 400 + i * 0.05)):
            s.prices[(t, d.date().isoformat())] = {"ticker": t, "date": d.date().isoformat(),
                                                    "close": px, "adj_close": px, "volume": 1}
    return s


def ctx_for(store, ticker="AAPL", **kw):
    return ToolContext(store=store, retriever=Retriever(store, FakeEmbedder()), ticker=ticker, as_of=AS_OF,
                       run_id=1, model="test", allowed_tickers={"AAPL", "MSFT"},
                       on_call=store.log_tool_call, rerank=False, **kw)


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


class ScriptedLLM:
    """Replays replies; a callable reply gets the messages so it can read tool results."""

    model = "scripted"
    num_ctx = 8192

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    def chat(self, messages, tools):
        self.seen.append(messages)
        if not self.replies:
            return {"role": "assistant", "content": "I am done.", "tool_calls": []}
        r = self.replies.pop(0)
        return r(messages) if callable(r) else r


def first_citation(messages):
    for m in reversed(messages):
        if m["role"] == "tool" and m["tool_name"] == "search_knowledge":
            return re.search(r"chunk_\d+", m["content"]).group(0)
    raise AssertionError("no search result in conversation")


WRITE_UP = dict(
    bull_case="Guidance was raised and demand came in above expectations, so estimates may move higher.",
    bear_case="The stock already prices in strong demand; any slowdown in orders would hurt sentiment.",
    catalysts=["Next quarterly earnings report", "Product launch event"],
    valuation="Valuation looks full versus history but is supported by strong cash generation.",
)


def save(horizon, cite=True, thesis=None, **extra):
    def reply(messages):
        sources = [first_citation(messages)] if cite else ["chunk_999999"]
        return call("save_suggestion", horizon=horizon, stance="bullish",
                    thesis=thesis or "Demand came in above expectations and guidance was raised, per the cited news.",
                    risks=["Valuation", "Macro slowdown"], sources=sources, confidence=0.6, **{**WRITE_UP, **extra})
    return reply


HAPPY = [call("get_features"), call("search_knowledge", query="demand and guidance"), save("medium"), save("long")]


# ------------------------------------------------------------------ number grounding
@pytest.mark.parametrize("text,sources,bad", [
    ("Revenue grew 15.1% year on year.", [0.151], []),
    ("TTM revenue reached $400.4B.", [400400000000.0], []),
    ("Trades at 39.3x earnings.", [39.258], []),
    ("Shares fell 12% from the high.", [-0.1203], []),
    ("The 10-year yield is 4.1%.", [4.1], []),
    ("Margins expanded to 31%.", [0.276], ["31%"]),
    ("Q3 2026 results; S&P 500 member; 3 segments; 10-K risks.", [], []),
    ("EPS of $8.97 and growth of 22.5%", [8.97], ["22.5%"]),
])
def test_unsupported_numbers(text, sources, bad):
    assert unsupported_numbers(text, sources) == bad


def test_source_numbers_reads_json_and_scientific():
    assert source_numbers(['{"a":0.151,"b":-4e9,"c":"x"}']) == [0.151, 4e9]


# ------------------------------------------------------------------ text tool-call fallback
def test_parse_text_tool_calls():
    qwen = 'Sure.\n<tool_call>\n{"name": "get_macro", "arguments": {}}\n</tool_call>'
    assert parse_text_tool_calls(qwen) == [{"function": {"name": "get_macro", "arguments": {}}}]
    bare = '```json\n{"name": "get_features", "arguments": "{\\"ticker\\": \\"AAPL\\"}"}\n```'
    assert parse_text_tool_calls(bare)[0]["function"]["arguments"] == {"ticker": "AAPL"}
    assert parse_text_tool_calls("Just prose, no calls.") == []


# ------------------------------------------------------------------ agent loop
def test_happy_path_saves_both_horizons(store):
    ctx = ctx_for(store)
    res = run_ticker(ScriptedLLM(HAPPY), ctx)
    assert res.complete and res.error is None and res.steps == 4
    rows = store.suggestions
    assert set(rows) == {("AAPL", "medium", "2026-11-11"), ("AAPL", "long", "2026-11-11")}
    row = rows[("AAPL", "long", "2026-11-11")]
    assert row["run_id"] == 1 and row["model"] == "test" and row["sources"][0].startswith("chunk_")
    assert [c["tool"] for c in store.tool_calls] == ["get_features", "search_knowledge",
                                                      "save_suggestion", "save_suggestion"]


def test_rejects_unseen_citation_then_accepts_fix(store):
    llm = ScriptedLLM([call("search_knowledge", query="demand"), save("medium", cite=False),
                       save("medium"), save("long")])
    res = run_ticker(llm, ctx_for(store))
    assert res.complete
    rejection = [m for m in llm.seen[2] if m["role"] == "tool"][-1]["content"]
    assert rejection.startswith("ERROR") and "chunk_999999" in rejection


def test_rejects_invented_numbers(store):
    llm = ScriptedLLM([call("search_knowledge", query="demand"),
                       save("medium", thesis="Revenue will grow 37.5% next year according to my own estimate."),
                       save("medium"), save("long")])
    res = run_ticker(llm, ctx_for(store))
    assert res.complete
    assert "37.5%" in [m for m in llm.seen[2] if m["role"] == "tool"][-1]["content"]


def test_model_cannot_override_ticker_or_as_of(store):
    llm = ScriptedLLM([call("search_knowledge", query="demand"),
                       save("medium", ticker="MSFT", as_of="2030-01-01"), save("long")])
    run_ticker(llm, ctx_for(store))
    assert {k[0] for k in store.suggestions} == {"AAPL"}
    assert {k[2] for k in store.suggestions} == {"2026-11-11"}


def test_tools_are_bound_to_as_of_and_watchlist(store):
    ctx = ctx_for(store)
    assert "not on the watchlist" in ctx.execute("get_features", {"ticker": "TSLA"})
    feats = json.loads(ctx.execute("get_features", {}))
    assert feats["as_of"] == "2026-11-11" and feats["price"]["last_date"] < "2026-11-11"
    assert "unknown tool" in ctx.execute("place_trade", {"qty": 100})
    assert "bad arguments" in ctx.execute("get_macro", {"as_of": "2030-01-01"})
    weekly = json.loads(ctx.execute("get_prices", {"weeks": 4}))["weekly_close"]
    assert len(weekly) == 4 and max(weekly) < "2026-11-11"


def test_nudges_then_hits_step_cap(store):
    llm = ScriptedLLM([])  # never calls a tool
    res = run_ticker(llm, ctx_for(store), max_steps=3)
    assert not res.complete and "step cap" in res.error and res.steps == 3
    assert "have not saved the medium and long" in llm.seen[1][-1]["content"]


def test_tool_call_cap(store):
    res = run_ticker(ScriptedLLM([call("get_macro")] * 10), ctx_for(store), max_tool_calls=3)
    assert "tool-call cap" in res.error and res.tool_calls == 3


def test_no_write_tools_besides_save():
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert names == {"search_knowledge", "get_features", "get_prices", "get_macro", "save_suggestion"}
    for spec in TOOL_SPECS:  # the model is never offered an as_of parameter
        assert "as_of" not in spec["function"]["parameters"]["properties"]


def test_fit_context_trims_oldest_tool_results_only():
    msgs = [{"role": "system", "content": "S" * 5000}, {"role": "user", "content": "go"}]
    msgs += [{"role": "tool", "tool_name": "x", "content": "R" * 4000} for _ in range(8)]
    trimmed = fit_context(msgs, budget_tokens=6000)
    assert trimmed > 0 and msgs[0]["content"] == "S" * 5000
    assert msgs[2].get("_trimmed") and not msgs[-1].get("_trimmed")
    assert agent_mod.estimate_tokens(msgs) <= 6000


# ------------------------------------------------------------------ weekly run + delivery
def test_weekly_run_partial_with_retry_and_digest(store):
    replies = (HAPPY  # AAPL succeeds
               + [call("search_knowledge", query="demand"), save("medium")]  # MSFT gets medium only...
               + [call("get_macro")] * 2)  # ...then stalls; the retry also stalls
    llm = ScriptedLLM(replies)
    sent = []
    status, results, failures = weekly_run(["AAPL", "MSFT"], AS_OF, store, Retriever(store, FakeEmbedder(), reranker=FakeReranker()),
                                           llm, notify=sent.append, max_steps=4, retries=1)
    assert status == "partial" and list(failures) == ["MSFT"]
    assert set(results[1].saved) == {"medium"}  # kept across the retry
    assert store.agent_runs[1]["status"] == "partial" and "MSFT" in store.agent_runs[1]["error"]
    digest = sent[0]
    assert "AAPL" in digest and "6-24m: bullish (confidence 0.60)" in digest
    assert "Not completed: MSFT" in digest and telegram.DISCLAIMER in digest


def test_weekly_run_crash_marks_error_and_alerts(store):
    class Boom(ScriptedLLM):
        def chat(self, messages, tools):
            raise RuntimeError("GPU fell off")

    sent = []
    with pytest.raises(RuntimeError):
        weekly_run(["AAPL"], AS_OF, store, None, Boom([]), notify=sent.append)
    assert store.agent_runs[1]["status"] == "error" and "crashed" in sent[0]


def test_telegram_split_and_send():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    parts = telegram.split_message(text, limit=1000)
    assert all(len(p) <= 1000 for p in parts) and "\n".join(parts) == text
    assert telegram.split_message("y" * 2500, limit=1000) == ["y" * 1000, "y" * 1000, "y" * 500]

    class Session:
        def __init__(self):
            self.posts = []

        def post(self, url, json, timeout):
            self.posts.append(json)
            return type("R", (), {"status_code": 200, "text": "ok"})()

    s = Session()
    assert telegram.send("hello", token="t", chat_id="c", session=s) is True
    assert s.posts == [{"chat_id": "c", "text": "hello", "disable_web_page_preview": True}]


def test_telegram_unconfigured(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram.send("hello") is False


# ------------------------------------------------------------------ Ollama client
class _Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class _OllamaSession:
    def __init__(self, chat_reply, models=("trading-analyst:latest",)):
        self.chat_reply, self._models, self.payloads = chat_reply, models, []

    def get(self, url, timeout):
        return _Resp({"models": [{"name": m} for m in self._models]})

    def post(self, url, json, timeout):
        self.payloads.append(json)
        return _Resp({"message": self.chat_reply})


def test_ollama_client_structured_and_text_calls():
    s = _OllamaSession({"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": "get_macro", "arguments": {}}}]})
    c = OllamaClient(url="http://x", model="trading-analyst", session=s)
    c.check()
    out = c.chat([{"role": "user", "content": "hi"}], TOOL_SPECS)
    assert out["tool_calls"][0]["function"]["name"] == "get_macro"
    assert s.payloads[0]["options"]["num_ctx"] == c.num_ctx and s.payloads[0]["stream"] is False

    s2 = _OllamaSession({"role": "assistant",
                         "content": '<tool_call>{"name": "get_features", "arguments": {}}</tool_call>'})
    assert OllamaClient(url="http://x", session=s2).chat([], [])["tool_calls"][0]["function"]["name"] == "get_features"


def test_ollama_client_missing_model():
    with pytest.raises(LLMError, match="ollama create"):
        OllamaClient(url="http://x", model="trading-analyst", session=_OllamaSession({}, models=("qwen2.5:7b",))).check()


def test_ollama_think_on_and_fallback_for_models_without_it():
    class ThinkSession(_OllamaSession):
        def post(self, url, json, timeout):
            self.payloads.append(dict(json))
            if json["think"] and self.reject_think:
                r = _Resp({}, status=400)
                r.text = '{"error":"model does not support thinking"}'
                return r
            return _Resp({"message": {"role": "assistant", "content": "ok", "thinking": "let me check..."}})

    s = ThinkSession({})
    s.reject_think = False
    c = OllamaClient(url="http://x", think=True, session=s)
    c.chat([], [])
    assert s.payloads[0]["think"] is True and c.last_thinking == "let me check..."

    s2 = ThinkSession({})
    s2.reject_think = True
    c2 = OllamaClient(url="http://x", think=True, session=s2)
    assert c2.chat([], [])["content"] == "ok"
    assert [p["think"] for p in s2.payloads] == [True, False] and c2.think is False
    c2.chat([], [])
    assert s2.payloads[-1]["think"] is False  # remembered: no second failed attempt


def test_numbers_with_units_in_passages_are_sources():
    passage = '[{"id":"chunk_1","text":"The Board authorized $100 billion of share repurchases."}]'
    assert unsupported_numbers("A $100B buyback supports the stock.", source_numbers([passage])) == []
    assert unsupported_numbers("A $90B buyback supports the stock.", source_numbers([passage])) == ["$90B"]
    assert unsupported_numbers("Revenue base of $478.8B.", source_numbers(['{"revenue_ttm":478834000000}'])) == []


def test_ollama_retries_model_load_oom_then_succeeds():
    class Flaky(_OllamaSession):
        def __init__(self):
            super().__init__({"role": "assistant", "content": "ok"})
            self.fail = 2

        def post(self, url, json, timeout):
            self.payloads.append((url, dict(json)))
            if self.fail:
                self.fail -= 1
                r = _Resp({}, status=500)
                r.text = '{"error":"llama-server reported out-of-memory during startup: cudaMalloc failed"}'
                return r
            r = _Resp({"message": self.chat_reply})
            r.text = ""
            return r

    s = Flaky()
    c = OllamaClient(url="http://x", session=s)
    waits = []
    c._sleep = waits.append
    assert c.chat([], [])["content"] == "ok"
    assert waits == [15.0, 30.0] and s.payloads[-1][1]["keep_alive"] == "30m"

    s2 = Flaky()
    s2.fail = 99
    c2 = OllamaClient(url="http://x", session=s2)
    c2._sleep = lambda _: None
    with pytest.raises(LLMError, match="short on memory"):
        c2.warmup()
    assert s2.payloads[0][0].endswith("/api/generate") and len(s2.payloads) == 4  # 1 + 3 retries


def test_field_names_and_dates_are_not_number_sources():
    feats = '{"price":{"sma_50":180.2,"ret_12m":0.28,"last_date":"2026-11-10"},"fundamentals":{"net_margin":0.32}}'
    src = source_numbers([feats])
    assert unsupported_numbers("Net margin of 50%.", src) == ["50%"]       # "50" only exists in a key
    assert unsupported_numbers("Up 12.0% over a year.", src) == ["12.0%"]  # "12" only in "ret_12m"
    assert unsupported_numbers("Net margin of 32%; up 28% in a year.", src) == []
    assert unsupported_numbers("Moved 11.0%.", src) == ["11.0%"]          # "11" only in the date


def test_non_english_text_is_rejected_so_the_model_rewrites_it():
    import pytest as _pt
    from pydantic import ValidationError
    from agent.schema import Suggestion
    base = dict(ticker="AAPL", horizon="long", stance="neutral", sources=["chunk_1"], confidence=0.55,
                as_of="2026-11-11", thesis="Fundamentals remain solid with steady services growth and buybacks.",
                **WRITE_UP)
    Suggestion(**base, risks=["AI adoption slower than expected"])
    with _pt.raises(ValidationError, match="English"):
        Suggestion(**base, risks=["AI adoption不及预期"])
    with _pt.raises(ValidationError, match="English"):
        Suggestion(**{**base, "thesis": base["thesis"] + " 增长强劲。"}, risks=["Valuation"])



def test_write_up_fields_are_required_and_number_checked(store):
    from agent.schema import Suggestion
    import pytest as _pt
    from pydantic import ValidationError
    base = dict(ticker="AAPL", horizon="long", stance="neutral", sources=["chunk_1"], confidence=0.55,
                as_of="2026-11-11", thesis="Fundamentals remain solid with steady services growth and buybacks.",
                risks=["Valuation"])
    with _pt.raises(ValidationError, match="bull_case"):
        Suggestion(**base)
    s = Suggestion(**base, **{**WRITE_UP, "valuation": "Trades at 99.9x earnings, far above peers."})
    assert "99.9x" in s.text_for_checks()            # the valuation text goes through the number check
    assert s.to_row(1, "m")["catalysts"] == WRITE_UP["catalysts"]
