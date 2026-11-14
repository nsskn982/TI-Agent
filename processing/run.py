"""M2 processing: clean -> chunk -> embed -> store, for every unprocessed document.

    python -m processing.run
    python -m processing.run --max-docs 50

Re-running is safe: a document's chunks are replaced, and documents that fail
are flagged with process_error so they are not retried forever.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from common import logging_setup, progress
from common.text import normalize
from processing.chunk import chunk_text

log = logging.getLogger("processing")


def build_chunks(doc: dict, embedder) -> list[dict]:
    body = normalize(doc.get("body") or "")
    title = normalize(doc.get("title") or "")
    if doc["source"] == "news":
        # News is headline + short summary: keep it as one chunk.
        pieces = [f"{title}\n{body}".strip()]
    else:
        pieces = chunk_text(body)
    pieces = [p for p in pieces if p]
    if not pieces:
        return []

    # Prefix with context so a chunk embeds as "AAPL 10-K ..." rather than floating text.
    header = f"{doc['ticker']} {doc.get('doc_type') or doc['source']}"
    vectors = embedder.encode([f"{header}: {p}" for p in pieces])
    return [
        {
            "document_id": doc["id"],
            "ticker": doc["ticker"],
            "source": doc["source"],
            "doc_type": doc.get("doc_type"),
            "published_at": doc["published_at"],
            "chunk_index": i,
            "content": p,
            "embedding": v,
        }
        for i, (p, v) in enumerate(zip(pieces, vectors))
    ]


def out_of_memory(exc: BaseException) -> bool:
    """The machine ran out of memory (not this document's fault): stop instead of marking it failed."""
    return isinstance(exc, MemoryError) or getattr(exc, "winerror", None) == 1455 or "paging file is too small" in str(exc)


def _count(store, method: str) -> int | None:
    try:
        return getattr(store, method)() if hasattr(store, method) else None
    except Exception:
        return None


def process(store, embedder, max_docs: int | None = None, batch_size: int = 25) -> dict:
    total = _count(store, "count_unprocessed")
    if max_docs is not None and total is not None:
        total = min(total, max_docs)
    with progress.step("Chunk + embed", total=total) as st:
        stats = _process(store, embedder, max_docs, batch_size, st)
        st.set_result(f"{stats['chunks']:,} chunks")
    return stats


def _process(store, embedder, max_docs, batch_size, st) -> dict:
    stats = {"documents": 0, "chunks": 0, "failed": 0, "errors": []}
    while max_docs is None or stats["documents"] + stats["failed"] < max_docs:
        limit = batch_size if max_docs is None else min(batch_size, max_docs - stats["documents"] - stats["failed"])
        docs = store.fetch_unprocessed(limit)
        if not docs:
            break
        for doc in docs:
            try:
                rows = build_chunks(doc, embedder)
                store.replace_chunks(doc["id"], rows)
                store.mark_processed(doc["id"], datetime.now(timezone.utc).isoformat())
                stats["documents"] += 1
                stats["chunks"] += len(rows)
                st.advance(note=f"{doc.get('ticker', '')} {doc.get('doc_type') or doc.get('source', '')}".strip())
            except Exception as exc:
                if out_of_memory(exc):
                    log.error("Out of memory: stopping processing (documents stay queued). Close apps or "
                              "enlarge the Windows page file, then run again.")
                    raise
                log.exception("Document %s failed", doc.get("id"))
                msg = f"{type(exc).__name__}: {exc}"
                store.mark_failed(doc["id"], msg)
                stats["failed"] += 1
                stats["errors"].append({"document_id": doc.get("id"), "error": msg[:500]})
                st.problem()
                st.advance()
        log.info("Progress: %d docs, %d chunks, %d failed", stats["documents"], stats["chunks"], stats["failed"])
    return stats


def score_sentiment(store, scorer, max_docs: int | None = None, batch_size: int = 200) -> int:
    """FinBERT-score every news doc without a score (also backfills older news)."""
    total = _count(store, "count_unscored_news")
    with progress.step("News sentiment", total=total) as st:
        scored = _score(store, scorer, max_docs, batch_size, st)
        st.set_result(f"{scored:,} scored")
    return scored


def _score(store, scorer, max_docs, batch_size, st) -> int:
    scored = 0
    seen: set[int] = set()
    while max_docs is None or scored < max_docs:
        docs = [d for d in store.fetch_unscored_news(batch_size) if d["id"] not in seen]
        if not docs:  # also guards against an update that silently matched nothing
            break
        seen.update(d["id"] for d in docs)
        texts = [f"{normalize(d.get('title') or '')}. {normalize(d.get('body') or '')[:600]}" for d in docs]
        results = scorer.score(texts)
        store.set_sentiment([{"id": d["id"], "sentiment": s, "label": l} for d, (s, l) in zip(docs, results)])
        scored += len(docs)
        st.advance(len(docs))
        log.info("Sentiment: %d news docs scored", scored)
    return scored


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    p = argparse.ArgumentParser(description="TI Agent processing + embedding (M2)")
    p.add_argument("--max-docs", type=int, default=None)
    p.add_argument("--skip-sentiment", action="store_true")
    args = p.parse_args(argv)

    from common.store import Store
    from processing.embed import Embedder

    started = datetime.now(timezone.utc)
    store = Store()
    steps = ["Load models", "Chunk + embed"] + ([] if args.skip_sentiment else ["News sentiment"])
    with progress.workflow("Processing", steps):
        return _main(args, store, started, Embedder)


def _main(args, store, started, Embedder) -> int:
    with progress.step("Load models"):
        embedder = Embedder()
        embedder.encode(["warm-up"])  # loads MiniLM now, so the embed step's timer is the real work
    stats = process(store, embedder, args.max_docs)

    if not args.skip_sentiment:
        from processing.sentiment import SentimentScorer

        try:
            stats["sentiment"] = score_sentiment(store, SentimentScorer())
        except Exception as exc:
            log.exception("Sentiment scoring failed")
            stats["failed"] += 1
            stats["errors"].append({"stage": "sentiment", "error": f"{type(exc).__name__}: {exc}"[:500]})

    status = "ok" if not stats["failed"] else ("error" if not stats["documents"] else "partial")
    log.info("Done: status=%s %s", status, {k: v for k, v in stats.items() if k != "errors"})
    store.log_run(
        {
            "job": "processing",
            "started_at": started.isoformat(),
            "status": status,
            "counts": {k: stats.get(k, 0) for k in ("documents", "chunks", "failed", "sentiment")},
            "errors": stats["errors"],
        }
    )
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
