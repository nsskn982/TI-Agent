"""Supabase access layer. Every module reads/writes through this.

Kept deliberately thin so tests can substitute an in-memory fake with the
same method names (see tests/fakes.py).
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

from common.config import require

log = logging.getLogger(__name__)

BATCH = 500


def _batches(rows: Sequence[dict], size: int = BATCH) -> Iterable[Sequence[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


class Store:
    def __init__(self, client: Any | None = None):
        if client is None:
            from supabase import create_client

            client = create_client(require("SUPABASE_URL"), require("SUPABASE_SERVICE_KEY"))
        self.db = client

    # ------------------------------------------------------------ writes
    def _upsert(self, table: str, rows: Sequence[dict], on_conflict: str, ignore_duplicates: bool = False) -> int:
        n = 0
        for batch in _batches(list(rows)):
            self.db.table(table).upsert(
                list(batch), on_conflict=on_conflict, ignore_duplicates=ignore_duplicates
            ).execute()
            n += len(batch)
        return n

    def upsert_tickers(self, rows: Sequence[dict]) -> int:
        return self._upsert("tickers", rows, "symbol")

    def upsert_prices(self, rows: Sequence[dict]) -> int:
        return self._upsert("prices", rows, "ticker,date")

    def upsert_macro(self, rows: Sequence[dict]) -> int:
        return self._upsert("macro_series", rows, "series_id,date")

    def insert_documents(self, rows: Sequence[dict]) -> int:
        # ignore_duplicates: never reset processed_at on documents we already have.
        return self._upsert("documents", rows, "ticker,source,source_id", ignore_duplicates=True)

    def replace_chunks(self, document_id: int, rows: Sequence[dict]) -> int:
        self.db.table("chunks").delete().eq("document_id", document_id).execute()
        n = 0
        for batch in _batches(list(rows), 200):
            self.db.table("chunks").insert(list(batch)).execute()
            n += len(batch)
        return n

    def mark_processed(self, document_id: int, processed_at: str) -> None:
        self.db.table("documents").update({"processed_at": processed_at, "process_error": None}).eq(
            "id", document_id
        ).execute()

    def mark_failed(self, document_id: int, error: str) -> None:
        self.db.table("documents").update({"process_error": error[:2000]}).eq("id", document_id).execute()

    def log_run(self, row: dict) -> None:
        try:
            self.db.table("ingestion_runs").insert(row).execute()
        except Exception:  # logging must never break the pipeline
            log.exception("Could not write ingestion_runs row")

    # ------------------------------------------------------------ reads
    def fetch_unprocessed(self, limit: int = 25) -> list[dict]:
        res = (
            self.db.table("documents")
            .select("id,ticker,source,doc_type,title,published_at,body")
            .is_("processed_at", "null")
            .is_("process_error", "null")
            .order("ingested_at")
            .limit(limit)
            .execute()
        )
        return list(res.data or [])

    def existing_source_ids(self, ticker: str, source: str) -> set[str]:
        res = (
            self.db.table("documents")
            .select("source_id")
            .eq("ticker", ticker)
            .eq("source", source)
            .execute()
        )
        return {r["source_id"] for r in (res.data or [])}

    def active_tickers(self) -> list[str]:
        res = self.db.table("tickers").select("symbol").eq("active", True).execute()
        return [r["symbol"] for r in (res.data or [])]
