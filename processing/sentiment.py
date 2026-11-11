"""FinBERT headline sentiment: score = p(positive) - p(negative), in [-1, 1]."""
from __future__ import annotations

from typing import Sequence

from common.config import env

DEFAULT_MODEL = "ProsusAI/finbert"


class SentimentScorer:
    def __init__(self, model_name: str | None = None, batch_size: int = 32):
        self.model_name = model_name or env("SENTIMENT_MODEL", DEFAULT_MODEL)
        self.batch_size = batch_size
        self._tok = self._model = None

    def _load(self):
        if self._model is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tok = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name).eval()
            labels = {i: l.lower() for i, l in self._model.config.id2label.items()}
            self._pos = next(i for i, l in labels.items() if l.startswith("pos"))
            self._neg = next(i for i, l in labels.items() if l.startswith("neg"))
            self._labels = labels

    def score(self, texts: Sequence[str]) -> list[tuple[float, str]]:
        if not texts:
            return []
        self._load()
        import torch

        out: list[tuple[float, str]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = list(texts[i : i + self.batch_size])
            enc = self._tok(batch, padding=True, truncation=True, max_length=256, return_tensors="pt")
            with torch.no_grad():
                probs = torch.softmax(self._model(**enc).logits, dim=-1)
            for p in probs:
                score = float(p[self._pos] - p[self._neg])
                out.append((round(score, 4), self._labels[int(p.argmax())]))
        return out
