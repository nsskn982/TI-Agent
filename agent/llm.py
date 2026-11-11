"""Minimal Ollama chat client with tool calling."""
from __future__ import annotations

import json
import re
import uuid

import requests

from common.config import env, env_int

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

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        payload = {
            "model": self.model, "messages": messages, "tools": tools, "stream": False,
            "think": self.think,
            # Sampling comes from the Modelfile (Qwen's recommended settings for thinking mode)
            # unless a temperature is passed explicitly.
            "options": {"num_ctx": self.num_ctx}
            | ({"temperature": self.temperature} if self.temperature is not None else {}),
        }
        try:
            resp = self.session.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
            if resp.status_code == 400 and self.think and "think" in resp.text.lower():
                # Model without thinking support (e.g. qwen2.5): retry plain and remember.
                self.think = False
                payload["think"] = False
                resp = self.session.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"Ollama chat failed: {exc}") from exc
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
