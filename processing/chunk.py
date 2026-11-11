"""Sentence-aware chunking sized for MiniLM (256 word-piece limit => ~180 words)."""
from __future__ import annotations

import re

_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9\"'(\[])|\n{2,}")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s and s.strip()]


def chunk_text(text: str, max_words: int = 180, overlap_words: int = 30, min_words: int = 8) -> list[str]:
    if overlap_words >= max_words:
        raise ValueError("overlap_words must be smaller than max_words")

    # Break over-long sentences (tables, lists) into hard word windows first.
    units: list[list[str]] = []
    for sent in split_sentences(text):
        words = sent.split()
        for i in range(0, len(words), max_words):
            units.append(words[i : i + max_words])

    chunks: list[str] = []
    current: list[list[str]] = []
    size = 0
    for unit in units:
        if current and size + len(unit) > max_words:
            chunks.append(" ".join(w for u in current for w in u))
            # Carry trailing sentences forward as overlap.
            carry: list[list[str]] = []
            carried = 0
            for u in reversed(current):
                if carried + len(u) > overlap_words:
                    break
                carry.insert(0, u)
                carried += len(u)
            current, size = carry, carried
        current.append(unit)
        size += len(unit)
    if current:
        tail = " ".join(w for u in current for w in u)
        if not chunks or size >= min_words:
            chunks.append(tail)

    return [c for c in chunks if c.strip()]
