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
        self.fundamentals: list[dict] = []
        self.rpc_calls: list[tuple] = []
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

    # ---------------------------------------------------------------- phase 2
    def upsert_fundamentals(self, rows):
        self.fundamentals.extend(rows)
        return len(rows)

    def get_prices(self, ticker, start, before):
        rows = [r for (t, d), r in self.prices.items() if t == ticker and start.isoformat() <= d < before.isoformat()]
        return sorted(rows, key=lambda r: r["date"])

    def get_macro(self, series_ids, start, before):
        rows = [r for (s, d), r in self.macro.items()
                if s in series_ids and start.isoformat() <= d < before.isoformat()]
        return sorted(rows, key=lambda r: r["date"])

    def get_fundamentals(self, ticker, before):
        return [r for r in self.fundamentals
                if r["ticker"] == ticker and r["filed"] < before.isoformat()]

    def get_news_sentiment(self, ticker, start, before):
        return [{"published_at": d["published_at"], "sentiment": d["sentiment"]} for d in self.documents.values()
                if d["ticker"] == ticker and d["source"] == "news" and d.get("sentiment") is not None
                and start.isoformat() <= d["published_at"] < before.isoformat()]

    def fetch_unscored_news(self, limit=200):
        return [dict(d) for d in self.documents.values()
                if d["source"] == "news" and d.get("scored_at") is None][:limit]

    def set_sentiment(self, rows):
        for r in rows:
            d = self.documents[r["id"]]
            d.update(sentiment=r["sentiment"], sentiment_label=r["label"], scored_at="now")
        return len(rows)

    def get_document_meta(self, ids):
        return {i: {"id": i, "title": self.documents[i].get("title"), "url": self.documents[i].get("url")}
                for i in ids if i in self.documents}

    def rpc(self, name, params):
        """Mimics match_chunks / keyword_chunks over stored chunks."""
        self.rpc_calls.append((name, params))
        rows = []
        for doc_id, chunks in self.chunks.items():
            for i, c in enumerate(chunks):
                if c["published_at"] >= params["as_of"]:
                    continue
                if params.get("filter_ticker") and c["ticker"] != params["filter_ticker"]:
                    continue
                if params.get("filter_source") and c["source"] != params["filter_source"]:
                    continue
                rows.append({"id": doc_id * 1000 + i, **{k: c[k] for k in
                             ("document_id", "ticker", "source", "doc_type", "published_at", "content")},
                             "_emb": c["embedding"]})
        if name == "match_chunks":
            q = params["query_embedding"]
            rows.sort(key=lambda r: -sum(a * b for a, b in zip(q, r["_emb"])))
        elif name == "keyword_chunks":
            terms = {w.lower().strip("?.,") for w in params["query_text"].split() if len(w) > 3}
            rows = [r for r in rows if terms & set(r["content"].lower().split())]
            rows.sort(key=lambda r: -len(terms & set(r["content"].lower().split())))
        for r in rows:
            r.pop("_emb")
        return rows[: params["match_count"]]


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
