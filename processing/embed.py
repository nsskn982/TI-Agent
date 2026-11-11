"""Sentence-transformers embedder (all-MiniLM-L6-v2, 384 dims, normalised for cosine)."""
from __future__ import annotations

from typing import Sequence

from common.config import env

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384


class Embedder:
    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or env("EMBED_MODEL", DEFAULT_MODEL)
        self.device = device
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def encode(self, texts: Sequence[str], batch_size: int = 64) -> list[list[float]]:
        if not texts:
            return []
        vecs = self.model.encode(
            list(texts), batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        return [[round(float(x), 6) for x in v] for v in vecs]
