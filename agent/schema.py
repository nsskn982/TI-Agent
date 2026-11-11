"""Suggestion schema and the grounding checks applied before anything is saved."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CITATION = re.compile(r"^chunk_\d+$")


class Suggestion(BaseModel):
    """What the agent may write. ticker/as_of are injected by code, never by the model."""

    ticker: str
    horizon: Literal["medium", "long"]
    stance: Literal["bullish", "neutral", "bearish"]
    thesis: str = Field(min_length=40, max_length=1200)
    risks: list[str] = Field(min_length=1, max_length=5)
    sources: list[str] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0, le=1)
    as_of: date

    @field_validator("risks")
    @classmethod
    def _risks(cls, v: list[str]) -> list[str]:
        v = [r.strip() for r in v if r and r.strip()]
        if not v:
            raise ValueError("at least one non-empty risk is required")
        if any(len(r) > 300 for r in v):
            raise ValueError("each risk must be at most 300 characters")
        return v

    @field_validator("sources")
    @classmethod
    def _sources(cls, v: list[str]) -> list[str]:
        v = list(dict.fromkeys(s.strip() for s in v))
        bad = [s for s in v if not CITATION.match(s)]
        if bad:
            raise ValueError(f"sources must look like chunk_123; got {bad}")
        return v

    def to_row(self, run_id: int | None, model: str | None) -> dict:
        d = json.loads(self.model_dump_json())
        return {**d, "run_id": run_id, "model": model}


# ---------------------------------------------------------------- numbers come from code
# Only "claim-like" numbers are checked: anything with a decimal point, %, $, or a
# magnitude suffix. Plain integers (years, "3 risks", "S&P 500", "Q3") pass.
_CLAIM = re.compile(
    r"(?<![A-Za-z0-9.])(\$)?(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(%|percent|trillion|billion|million|tn|bn|mn|t|b|m|x)?(?![A-Za-z0-9])",
    re.I,
)
_SOURCE_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_SCALE = {"t": 1e12, "tn": 1e12, "trillion": 1e12, "b": 1e9, "bn": 1e9, "billion": 1e9,
          "m": 1e6, "mn": 1e6, "million": 1e6}


def _numbers_in_prose(text: str) -> list[float]:
    out = []
    for m in _SOURCE_NUM.findall(text):
        try:
            out.append(abs(float(m)))
        except ValueError:
            pass
    # Passages say "$100 billion": add the scaled value too, matching how claims are parsed.
    for m in _CLAIM.finditer(text):
        unit = (m.group(3) or "").lower()
        if unit in _SCALE:
            out.append(abs(float(m.group(2).replace(",", ""))) * _SCALE[unit])
    return out


def _walk(obj, out: list[float]) -> None:
    """Collect numeric *values* from parsed JSON. Keys are skipped on purpose: a field
    name like `sma_50` or `ret_12m` must not count as evidence for "50%" or "12%"."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(abs(float(obj)))
    elif isinstance(obj, str):
        if not _DATE.match(obj):  # "2026-11-10" is a date, not the numbers 2026, 11, 10
            out.extend(_numbers_in_prose(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out)


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def source_numbers(texts: list[str]) -> list[float]:
    """Every number a tool returned: JSON values (not keys) and numbers in passage text."""
    out: list[float] = []
    for t in texts:
        try:
            _walk(json.loads(t.removesuffix("...[truncated]")), out)
        except (json.JSONDecodeError, ValueError):
            out.extend(_numbers_in_prose(t))  # plain-text or truncated result
    return out


def unsupported_numbers(text: str, sources: list[float]) -> list[str]:
    """Numeric claims in `text` that don't match any number a tool returned."""
    bad = []
    for m in _CLAIM.finditer(text):
        dollar, raw, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
        if not (dollar or unit or "." in raw):
            continue
        value = abs(float(raw.replace(",", "")))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tol = 0.5 * 10 ** -decimals + 1e-9
        candidates = []
        if unit in ("%", "percent"):
            candidates = [(value, tol), (value / 100, tol / 100)]  # 4.1% yield, or 0.151 growth
        elif unit in _SCALE:
            candidates = [(value * _SCALE[unit], tol * _SCALE[unit])]
        else:  # $12.37, 39.3, 22x
            candidates = [(value, tol)]
        ok = any(abs(c - abs(s)) <= max(t, abs(c) * 0.005) for c, t in candidates for s in sources)
        if not ok:
            bad.append(m.group(0).strip())
    return bad
