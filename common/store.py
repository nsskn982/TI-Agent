"""Supabase access layer. Every module reads/writes through this.

Kept deliberately thin so tests can substitute an in-memory fake with the
same method names (see tests/fakes.py).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Iterable, Sequence

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

    def upsert_fundamentals(self, rows: Sequence[dict]) -> int:
        return self._upsert("fundamentals", rows, "ticker,concept,unit,period_start,period_end,accn")

    def set_sentiment(self, rows: Sequence[dict]) -> int:
        """rows: [{"id", "sentiment", "label"}] — one RPC per batch instead of one UPDATE per row."""
        n = 0
        for batch in _batches(list(rows), 200):
            res = self.db.rpc("set_sentiment", {"payload": list(batch)}).execute()
            n += int(res.data or 0)
        return n

    # ------------------------------------------------------------ agent (Phase 3)
    def start_agent_run(self, as_of: str, model: str | None) -> int:
        res = self.db.table("agent_runs").insert({"as_of": as_of, "model": model, "status": "running"}).execute()
        return int(res.data[0]["id"])

    def finish_agent_run(self, run_id: int, status: str, error: str | None = None) -> None:
        from datetime import datetime, timezone

        self.db.table("agent_runs").update({
            "status": status, "error": error, "finished_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", run_id).execute()

    def log_tool_call(self, row: dict) -> None:
        try:
            self.db.table("tool_calls").insert(row).execute()
        except Exception:  # an audit-log hiccup must not kill the agent run
            log.exception("Could not write tool_calls row")

    def upsert_suggestion(self, row: dict) -> None:
        self.db.table("suggestions").upsert(row, on_conflict="ticker,horizon,as_of").execute()

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

    # ------------------------------------------------------------ S&P 500 screen
    def sp500_symbols(self) -> list[str]:
        rows = self._select_all(lambda: self.db.table("tickers").select("symbol").eq("in_sp500", True).order("symbol"))
        return [r["symbol"] for r in rows]

    def upsert_screens(self, rows: Sequence[dict]) -> int:
        return self._upsert("screens", rows, on_conflict="as_of,ticker")

    def latest_selected(self) -> list[str]:
        """Tickers selected by the most recent screen, best rank first."""
        latest = (self.db.table("screens").select("as_of").eq("selected", True)
                  .order("as_of", desc=True).limit(1).execute().data)
        if not latest:
            return []
        rows = (self.db.table("screens").select("ticker,rank").eq("as_of", latest[0]["as_of"])
                .eq("selected", True).order("rank").execute().data or [])
        return [r["ticker"] for r in rows]

    def has_documents(self, ticker: str) -> bool:
        res = self.db.table("documents").select("id").eq("ticker", ticker).limit(1).execute()
        return bool(res.data)

    # PostgREST caps responses (1000 rows by default), so page through.
    def _select_all(self, build: Callable[[], Any], page: int = 1000) -> list[dict]:
        out: list[dict] = []
        start = 0
        while True:
            rows = build().range(start, start + page - 1).execute().data or []
            out.extend(rows)
            if len(rows) < page:
                return out
            start += page

    def get_prices(self, ticker: str, start: date, before: date) -> list[dict]:
        """Daily bars with start <= date < before (strictly before the as-of date)."""
        return self._select_all(
            lambda: self.db.table("prices")
            .select("date,close,adj_close,volume")
            .eq("ticker", ticker)
            .gte("date", start.isoformat())
            .lt("date", before.isoformat())
            .order("date")
        )

    def get_macro(self, series_ids: Sequence[str], start: date, before: date) -> list[dict]:
        return self._select_all(
            lambda: self.db.table("macro_series")
            .select("series_id,date,value")
            .in_("series_id", list(series_ids))
            .gte("date", start.isoformat())
            .lt("date", before.isoformat())
            .order("date")
        )

    def get_fundamentals(self, ticker: str, before: date) -> list[dict]:
        """Facts whose filing was public before the as-of date."""
        return self._select_all(
            lambda: self.db.table("fundamentals")
            .select("concept,unit,period_start,period_end,value,form,filed")
            .eq("ticker", ticker)
            .lt("filed", before.isoformat())
            .order("filed")
        )

    def get_news_sentiment(self, ticker: str, start: date, before: date) -> list[dict]:
        return self._select_all(
            lambda: self.db.table("documents")
            .select("published_at,sentiment")
            .eq("ticker", ticker)
            .eq("source", "news")
            .not_.is_("sentiment", "null")
            .gte("published_at", start.isoformat())
            .lt("published_at", before.isoformat())
            .order("published_at")
        )

    def fetch_unscored_news(self, limit: int = 200) -> list[dict]:
        res = (
            self.db.table("documents")
            .select("id,title,body")
            .eq("source", "news")
            .is_("scored_at", "null")
            .order("ingested_at")
            .limit(limit)
            .execute()
        )
        return list(res.data or [])

    def get_document_meta(self, ids: Sequence[int]) -> dict[int, dict]:
        if not ids:
            return {}
        res = self.db.table("documents").select("id,title,url").in_("id", list(ids)).execute()
        return {r["id"]: r for r in (res.data or [])}

    def rpc(self, name: str, params: dict) -> list[dict]:
        return list(self.db.rpc(name, params).execute().data or [])
