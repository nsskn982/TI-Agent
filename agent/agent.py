"""M6 AI Finance Agent: one tool-calling conversation per ticker (ReAct-style loop).

Guardrails enforced in code, not just in the prompt:
  * at most `max_steps` model turns and `max_tool_calls` tool calls per ticker
  * every tool call is logged (ToolContext.on_call -> tool_calls table)
  * the context is kept under budget, because Ollama silently drops the *oldest*
    messages (the system prompt and rules) when num_ctx overflows
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from agent.tools import TOOL_SPECS, ToolContext

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
CHARS_PER_TOKEN = 3.5
TOOL_SPEC_TOKENS = 900  # rough size of TOOL_SPECS once rendered into the prompt
TRIM_TO_CHARS = 400


@dataclass
class AgentResult:
    ticker: str
    saved: dict[str, dict] = field(default_factory=dict)
    steps: int = 0
    tool_calls: int = 0
    error: str | None = None

    @property
    def complete(self) -> bool:
        return set(self.saved) == {"medium", "long"}


def user_prompt(ticker: str, as_of: date) -> str:
    return (f"Analyse {ticker} as of {as_of.isoformat()}. Gather evidence with the tools, then save one "
            f"'medium' and one 'long' suggestion with save_suggestion.")


def estimate_tokens(messages: list[dict]) -> int:
    chars = sum(len(m.get("content") or "") + len(str(m.get("tool_calls") or "")) for m in messages)
    return int(chars / CHARS_PER_TOKEN) + TOOL_SPEC_TOKENS


def fit_context(messages: list[dict], budget_tokens: int) -> int:
    """Shrink the oldest tool results until the conversation fits. Returns how many were trimmed.

    Citations stay valid after trimming: ToolContext remembers every id it handed out.
    """
    trimmed = 0
    for m in messages:
        if estimate_tokens(messages) <= budget_tokens:
            break
        if m["role"] == "tool" and not m.get("_trimmed") and len(m["content"]) > TRIM_TO_CHARS:
            m["content"] = m["content"][:TRIM_TO_CHARS] + " ...[older result trimmed to save space]"
            m["_trimmed"] = True
            trimmed += 1
    return trimmed


def _wire(messages: list[dict]) -> list[dict]:
    """Strip private bookkeeping keys before sending to Ollama."""
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]


def run_ticker(llm, ctx: ToolContext, max_steps: int = 12, max_tool_calls: int = 16) -> AgentResult:
    result = AgentResult(ticker=ctx.ticker)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt(ctx.ticker, ctx.as_of)},
    ]
    budget = int(getattr(llm, "num_ctx", 8192) * 0.75)  # leave room for the reply

    while result.steps < max_steps and ctx.missing_horizons():
        fit_context(messages, budget)
        reply = llm.chat(_wire(messages), TOOL_SPECS)
        result.steps += 1
        ctx.step = result.steps
        calls = reply.get("tool_calls") or []
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls})

        if not calls:
            missing = ctx.missing_horizons()
            log.info("%s step %d: no tool call; still missing %s", ctx.ticker, result.steps, missing)
            messages.append({"role": "user", "content":
                             f"You have not saved the {' and '.join(missing)} suggestion(s) yet. "
                             f"Call save_suggestion now (gather more evidence first only if you must)."})
            continue

        for call in calls:
            if result.tool_calls >= max_tool_calls:
                result.error = f"tool-call cap ({max_tool_calls}) reached"
                break
            fn = call.get("function", {})
            name, args = fn.get("name", ""), fn.get("arguments") or {}
            out = ctx.execute(name, args if isinstance(args, dict) else {})
            result.tool_calls += 1
            log.info("%s step %d: %s -> %s", ctx.ticker, result.steps, name, out[:120].replace("\n", " "))
            messages.append({"role": "tool", "tool_name": name, "content": out})
        if result.error:
            break

    result.saved = dict(ctx.saved)
    if not result.complete and result.error is None:
        result.error = f"step cap ({max_steps}) reached; missing {ctx.missing_horizons()}"
    return result
