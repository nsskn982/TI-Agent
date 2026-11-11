"""In-memory stand-ins for Store and Embedder."""
from __future__ import annotations

import hashlib


class FakeStore:
    def __init__(self):
        self.tickers: dict[str, dict] = {}
        self.prices: dict[tuple, dict] = {}
        self.macro: dict[tuple, dict] = {}
        self.documents: dict[int, dict] = {}
        self.chunks: dict[int, list[dict]] = {}
        self.runs: list[dict] = []
        self._next_id = 1

    def upsert_tickers(self, rows):
        for r in rows:
            self.tickers.setdefault(r["symbol"], {}).update(r)
        return len(rows)

    def upsert_prices(self, rows):
        for r in rows:
            self.prices[(r["ticker"], r["date"])] = r
        return len(rows)

    def upsert_macro(self, rows):
        for r in rows:
            self.macro[(r["series_id"], r["date"])] = r
        return len(rows)

    def insert_documents(self, rows):
        keys = {(d["ticker"], d["source"], d["source_id"]) for d in self.documents.values()}
        for r in rows:
            k = (r["ticker"], r["source"], r["source_id"])
            if k in keys:
                continue
            keys.add(k)
            self.documents[self._next_id] = {**r, "id": self._next_id, "processed_at": None, "process_error": None}
            self._next_id += 1
        return len(rows)

    def existing_source_ids(self, ticker, source):
        return {d["source_id"] for d in self.documents.values() if d["ticker"] == ticker and d["source"] == source}

    def fetch_unprocessed(self, limit=25):
        out = [d for d in self.documents.values() if d["processed_at"] is None and d["process_error"] is None]
        return [dict(d) for d in out[:limit]]

    def replace_chunks(self, document_id, rows):
        self.chunks[document_id] = list(rows)
        return len(rows)

    def mark_processed(self, document_id, processed_at):
        self.documents[document_id]["processed_at"] = processed_at

    def mark_failed(self, document_id, error):
        self.documents[document_id]["process_error"] = error

    def log_run(self, row):
        self.runs.append(row)


class FakeEmbedder:
    dim = 384

    def __init__(self):
        self.calls: list[list[str]] = []

    def encode(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([h[i % len(h)] / 255 for i in range(self.dim)])
        return out
