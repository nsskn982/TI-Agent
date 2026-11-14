"""Minimal Ollama chat client with tool calling."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid

import requests

from common.config import env, env_int

log = logging.getLogger(__name__)

_TOOL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


class LLMError(RuntimeError):
    pass


def parse_text_tool_calls(content: str) -> list[dict]:
    """Small models sometimes write tool calls as text instead of structured calls.

    Handles Qwen's <tool_call>{...}</tool_call> and a bare {"name":..., "arguments":...} reply.
    """
    if not content:
        return []
    blobs = _TOOL_TAG.findall(content)
    stripped = content.strip().strip("`").removeprefix("json").strip()
    if not blobs and stripped.startswith("{"):
        blobs = [stripped]
    calls = []
    for blob in blobs:
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "name" in obj:
            args = obj.get("arguments") or obj.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"function": {"name": obj["name"], "arguments": args}})
    return calls


class OllamaClient:
    def __init__(self, url: str | None = None, model: str | None = None, num_ctx: int | None = None,
                 temperature: float | None = None, timeout: int = 900, think: bool | None = None,
                 session: requests.Session | None = None):
        self.url = (url or env("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or env("OLLAMA_MODEL", "trading-analyst")
        self.num_ctx = num_ctx or env_int("OLLAMA_CONTEXT_LENGTH", 16384)
        self.temperature = temperature
        self.timeout = timeout
        # Qwen3.5 can reason before answering. The reasoning is returned separately and
        # never sent back, so it costs time but not context.
        self.think = think if think is not None else (env("OLLAMA_THINK", "true") or "true").lower() != "false"
        self.session = session or requests.Session()
        self.last_thinking = ""
        # Keep the model resident between turns and tickers, so a weekly run loads it once.
        self.keep_alive = env("OLLAMA_KEEP_ALIVE", "30m")
        self.load_retries = 3
        self.retry_wait_s = 15.0
        self._sleep = time.sleep

    def models(self) -> list[str]:
        try:
            resp = self.session.get(f"{self.url}/api/tags", timeout=10)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"Ollama not reachable at {self.url}: {exc}") from exc
        return [m["name"] for m in resp.json().get("models", [])]

    def check(self) -> None:
        names = self.models()
        wanted = {self.model, f"{self.model}:latest"}
        if not wanted & set(names):
            raise LLMError(f"Model {self.model!r} not found in Ollama (have: {names}). "
                           f"Run: ollama create {self.model} -f agent/Modelfile")

    def _post(self, path: str, payload: dict) -> requests.Response:
        """POST with retries for model-load failures (e.g. Windows out of commit memory).

        Ollama loads the model lazily on the first request; if the machine is short on
        memory at that moment the load fails with HTTP 500 but succeeds once memory frees
        up, so wait and retry a few times instead of failing the whole ticker.
        """
        for attempt in range(self.load_retries + 1):
            try:
                resp = self.session.post(f"{self.url}{path}", json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                raise LLMError(f"Ollama request failed: {exc}") from exc
            body = getattr(resp, "text", "") or ""
            transient = resp.status_code >= 500 and any(
                k in body.lower() for k in ("memory", "load failed", "llama-server", "terminated"))
            if not transient or attempt == self.load_retries:
                return resp
            self._sleep(self.retry_wait_s * (attempt + 1))
        return resp  # pragma: no cover

    @staticmethod
    def _raise(resp: requests.Response, what: str) -> None:
        if resp.status_code >= 400:
            body = (getattr(resp, "text", "") or "")[:400]
            hint = (" (Ollama could not load the model: the machine is short on memory. Close memory-heavy "
                    "apps such as browser tabs, or enlarge the Windows page file.)") if "memory" in body.lower() else ""
            raise LLMError(f"{what}: HTTP {resp.status_code}: {body}{hint}")

    def unload(self) -> None:
        """Free the model's memory now instead of after keep_alive (the daily refresh may run next)."""
        try:
            self._post("/api/generate", {"model": self.model, "keep_alive": 0})
        except Exception as exc:  # best effort: Ollama frees it after keep_alive anyway
            log.warning("Could not unload %s: %s", self.model, exc)

    def warmup(self) -> None:
        """Load the model now, before the run allocates its own memory (embedder, reranker)."""
        resp = self._post("/api/generate", {"model": self.model, "prompt": "", "keep_alive": self.keep_alive,
                                            "options": {"num_ctx": self.num_ctx}})
        self._raise(resp, "Ollama model load failed")

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        payload = {
            "model": self.model, "messages": messages, "tools": tools, "stream": False,
            "think": self.think, "keep_alive": self.keep_alive,
            # Sampling comes from the Modelfile (Qwen's recommended settings for thinking mode)
            # unless a temperature is passed explicitly.
            "options": {"num_ctx": self.num_ctx}
            | ({"temperature": self.temperature} if self.temperature is not None else {}),
        }
        resp = self._post("/api/chat", payload)
        if resp.status_code == 400 and self.think and "think" in (getattr(resp, "text", "") or "").lower():
            # Model without thinking support (e.g. qwen2.5): retry plain and remember.
            self.think = False
            payload["think"] = False
            resp = self._post("/api/chat", payload)
        self._raise(resp, "Ollama chat failed")
        msg = resp.json().get("message") or {}
        self.last_thinking = msg.get("thinking") or ""
        calls = msg.get("tool_calls") or parse_text_tool_calls(msg.get("content", ""))
        for c in calls:
            c.setdefault("id", uuid.uuid4().hex[:8])
            args = c["function"].get("arguments")
            if isinstance(args, str):
                try:
                    c["function"]["arguments"] = json.loads(args)
                except json.JSONDecodeError:
                    c["function"]["arguments"] = {}
        return {"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls}
