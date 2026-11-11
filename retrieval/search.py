"""M5 hybrid retrieval: vector + keyword, fused with Reciprocal Rank Fusion.

Every query is bounded by an as-of date (published_at < as_of) inside the SQL
functions, so the agent cannot see the future even if the caller forgets.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone

log = logging.getLogger(__name__)

RRF_K = 60
DEFAULT_RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    ticker: str
    source: str
    doc_type: str | None
    published_at: str
    content: str
    score: float = 0.0
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None
    title: str | None = None
    url: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def citation(self) -> str:
        """The id the agent must cite in a suggestion's `sources`."""
        return f"chunk_{self.chunk_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["citation"] = self.citation
        d.pop("extra")
        return d


def as_of_ts(as_of: date | datetime) -> datetime:
    if isinstance(as_of, datetime):
        return as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    return datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)


def rrf(ranked_lists: list[list[dict]], k: int = RRF_K) -> dict[int, dict]:
    """{chunk_id: {"row": row, "score": sum 1/(k+rank), "ranks": [rank per list or None]}}"""
    fused: dict[int, dict] = {}
    for li, rows in enumerate(ranked_lists):
        for rank, row in enumerate(rows, start=1):
            entry = fused.setdefault(row["id"], {"row": row, "score": 0.0, "ranks": [None] * len(ranked_lists)})
            entry["score"] += 1.0 / (k + rank)
            entry["ranks"][li] = rank
    return fused


class Reranker:
    def __init__(self, model_name: str = DEFAULT_RERANKER):
        self.model_name = model_name
        self._model = None

    def score(self, query: str, passages: list[str]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return [float(s) for s in self._model.predict([(query, p) for p in passages])]


class Retriever:
    def __init__(self, store, embedder, reranker: Reranker | None = None):
        self.store = store
        self.embedder = embedder
        self.reranker = reranker

    def search(
        self,
        query: str,
        as_of: date | datetime,
        k: int = 8,
        ticker: str | None = None,
        source: str | None = None,
        rerank: bool = False,
        max_per_doc: int = 2,
        recency_half_life_days: float | None = None,
    ) -> list[Hit]:
        ts = as_of_ts(as_of)
        ticker = ticker.upper() if ticker else None
        pool = max(k * 5, 30)

        # Chunks were embedded as "TICKER FORM: text"; mirror that for the query.
        qvec = self.embedder.encode([f"{ticker}: {query}" if ticker else query])[0]
        vec_rows = self.store.rpc("match_chunks", {
            "query_embedding": qvec, "as_of": ts.isoformat(), "match_count": pool,
            "filter_ticker": ticker, "filter_source": source,
        })
        try:
            kw_rows = self.store.rpc("keyword_chunks", {
                "query_text": query, "as_of": ts.isoformat(), "match_count": pool,
                "filter_ticker": ticker, "filter_source": source,
            })
        except Exception as exc:  # keyword side is a booster, never a blocker
            log.warning("keyword search failed: %s", exc)
            kw_rows = []

        hits: list[Hit] = []
        for cid, e in rrf([vec_rows, kw_rows]).items():
            r = e["row"]
            published = str(r["published_at"])
            # Defence in depth: never return anything at/after as-of.
            if datetime.fromisoformat(published.replace("Z", "+00:00")) >= ts:
                continue
            score = e["score"]
            if recency_half_life_days:
                age = (ts - datetime.fromisoformat(published.replace("Z", "+00:00"))).total_seconds() / 86400
                score *= 0.5 ** (max(age, 0) / recency_half_life_days)
            hits.append(Hit(
                chunk_id=cid, document_id=r["document_id"], ticker=r["ticker"], source=r["source"],
                doc_type=r.get("doc_type"), published_at=published, content=r["content"], score=score,
                vector_rank=e["ranks"][0], keyword_rank=e["ranks"][1],
            ))
        hits.sort(key=lambda h: h.score, reverse=True)

        if rerank and hits:
            reranker = self.reranker or Reranker()
            self.reranker = reranker
            head = hits[: k * 4]
            for h, s in zip(head, reranker.score(query, [h.content for h in head])):
                h.rerank_score = s
            hits = sorted(head, key=lambda h: h.rerank_score, reverse=True) + hits[k * 4 :]

        # Diversity: at most max_per_doc chunks from one document (e.g. one long 10-K).
        out: list[Hit] = []
        per_doc: dict[int, int] = {}
        for h in hits:
            if per_doc.get(h.document_id, 0) >= max_per_doc:
                continue
            per_doc[h.document_id] = per_doc.get(h.document_id, 0) + 1
            out.append(h)
            if len(out) == k:
                break

        meta = self.store.get_document_meta(sorted({h.document_id for h in out}))
        for h in out:
            m = meta.get(h.document_id, {})
            h.title, h.url = m.get("title"), m.get("url")
        return out
