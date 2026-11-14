"""Local PostgreSQL access layer. Every module reads/writes through this.

Kept deliberately thin so tests can substitute an in-memory fake with the
same method names (see tests/fakes.py).

Rows come back as plain dicts with dates/timestamps as ISO strings, so callers
see the same shapes whatever the driver returns.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from typing import Any, Iterable, Sequence

from common.config import env

log = logging.getLogger(__name__)

BATCH = 500
DEFAULT_DATABASE_URL = "postgresql://ti_agent:ti_agent@127.0.0.1:5433/ti_agent"

# Functions callable through Store.rpc(); anything else is refused.
RPC_FUNCTIONS = {"match_chunks", "keyword_chunks", "set_sentiment"}


def database_url() -> str:
    return env("DATABASE_URL", DEFAULT_DATABASE_URL) or DEFAULT_DATABASE_URL


def _batches(rows: Sequence[dict], size: int = BATCH) -> Iterable[Sequence[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row(cursor) -> Any:
    names = [c.name for c in cursor.description]

    def make(values):
        return {n: _plain(v) for n, v in zip(names, values)}

    return make


def _vector(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


class Store:
    def __init__(self, url: str | None = None, connection: Any | None = None):
        self._url = url or database_url()
        self._conn = connection
        self._lock = threading.RLock()  # the website serves requests from several threads
        self._jsonb: dict[str, set[str]] = {}

    # ------------------------------------------------------------ plumbing
    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            import psycopg

            self._conn = psycopg.connect(self._url, autocommit=True)
            # Timestamps come back as UTC ISO strings whatever the server's time zone.
            self._conn.execute("set time zone 'UTC'")
        return self._conn

    def query(self, sql: str, params: Sequence | dict | None = None) -> list[dict]:
        with self._lock, self.conn.cursor(row_factory=_row) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall()) if cur.description else []

    def execute(self, sql: str, params: Sequence | dict | None = None) -> int:
        with self._lock, self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def _jsonb_columns(self, table: str) -> set[str]:
        if table not in self._jsonb:
            rows = self.query(
                "select column_name from information_schema.columns "
                "where table_schema = current_schema() and table_name = %s and data_type = 'jsonb'",
                (table,),
            )
            self._jsonb[table] = {r["column_name"] for r in rows}
        return self._jsonb[table]

    def _adapt(self, table: str, row: dict) -> dict:
        from psycopg.types.json import Jsonb

        jsonb = self._jsonb_columns(table)
        return {k: Jsonb(v) if k in jsonb and v is not None else v for k, v in row.items()}

    def _write(self, table: str, rows: Sequence[dict], on_conflict: str | None = None,
               ignore_duplicates: bool = False, returning: str | None = None) -> list[dict]:
        """INSERT (or upsert) rows, grouped by their key sets so missing keys keep column defaults."""
        from psycopg import sql

        keys = [k.strip() for k in on_conflict.split(",")] if on_conflict else []
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            groups.setdefault(tuple(r.keys()), []).append(self._adapt(table, r))

        out: list[dict] = []
        for cols, group in groups.items():
            stmt = sql.SQL("insert into {} ({}) values ({})").format(
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, cols)),
                sql.SQL(", ").join(sql.Placeholder(c) for c in cols),
            )
            if keys:
                updates = [c for c in cols if c not in keys]
                target = sql.SQL(", ").join(map(sql.Identifier, keys))
                if ignore_duplicates or not updates:
                    stmt += sql.SQL(" on conflict ({}) do nothing").format(target)
                else:
                    stmt += sql.SQL(" on conflict ({}) do update set {}").format(
                        target,
                        sql.SQL(", ").join(
                            sql.SQL("{0} = excluded.{0}").format(sql.Identifier(c)) for c in updates
                        ),
                    )
            if returning:
                stmt += sql.SQL(" returning {}").format(sql.SQL(returning))
            with self._lock, self.conn.cursor(row_factory=_row) as cur:
                if returning:
                    for r in group:
                        cur.execute(stmt, r)
                        out.extend(cur.fetchall())
                else:
                    cur.executemany(stmt, group)
        return out

    # ------------------------------------------------------------ writes
    def _upsert(self, table: str, rows: Sequence[dict], on_conflict: str, ignore_duplicates: bool = False) -> int:
        n = 0
        for batch in _batches(list(rows)):
            self._write(table, batch, on_conflict, ignore_duplicates)
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
        rows = [{**r, "embedding": _vector(r["embedding"])} if not isinstance(r.get("embedding"), str) else r
                for r in rows]
        with self._lock, self.conn.transaction():
            self.execute("delete from chunks where document_id = %s", (document_id,))
            for batch in _batches(rows, 200):
                self._write("chunks", batch)
        return len(rows)

    def mark_processed(self, document_id: int, processed_at: str) -> None:
        self.execute("update documents set processed_at = %s, process_error = null where id = %s",
                     (processed_at, document_id))

    def mark_failed(self, document_id: int, error: str) -> None:
        self.execute("update documents set process_error = %s where id = %s", (error[:2000], document_id))

    def upsert_fundamentals(self, rows: Sequence[dict]) -> int:
        return self._upsert("fundamentals", rows, "ticker,concept,unit,period_start,period_end,accn")

    def set_sentiment(self, rows: Sequence[dict]) -> int:
        """rows: [{"id", "sentiment", "label"}] — one statement per batch instead of one UPDATE per row."""
        from psycopg.types.json import Jsonb

        n = 0
        for batch in _batches(list(rows), 200):
            res = self.query("select set_sentiment(%s) as n", (Jsonb(list(batch)),))
            n += int(res[0]["n"] or 0)
        return n

    # ------------------------------------------------------------ agent (Phase 3)
    def start_agent_run(self, as_of: str, model: str | None) -> int:
        res = self._write("agent_runs", [{"as_of": as_of, "model": model, "status": "running"}], returning="id")
        return int(res[0]["id"])

    def finish_agent_run(self, run_id: int, status: str, error: str | None = None) -> None:
        self.execute("update agent_runs set status = %s, error = %s, finished_at = now() where id = %s",
                     (status, error, run_id))

    def log_tool_call(self, row: dict) -> None:
        try:
            self._write("tool_calls", [row])
        except Exception:  # an audit-log hiccup must not kill the agent run
            log.exception("Could not write tool_calls row")

    def upsert_suggestion(self, row: dict) -> None:
        self._write("suggestions", [row], on_conflict="ticker,horizon,as_of")

    def log_run(self, row: dict) -> None:
        try:
            self._write("ingestion_runs", [row])
        except Exception:  # logging must never break the pipeline
            log.exception("Could not write ingestion_runs row")

    # ------------------------------------------------------------ reads
    def fetch_unprocessed(self, limit: int = 25) -> list[dict]:
        return self.query(
            "select id, ticker, source, doc_type, title, published_at, body from documents "
            "where processed_at is null and process_error is null order by ingested_at limit %s",
            (limit,),
        )

    def existing_source_ids(self, ticker: str, source: str) -> set[str]:
        rows = self.query("select source_id from documents where ticker = %s and source = %s", (ticker, source))
        return {r["source_id"] for r in rows}

    def active_tickers(self) -> list[str]:
        return [r["symbol"] for r in self.query("select symbol from tickers where active")]

    # ------------------------------------------------------------ S&P 500 screen
    def sp500_symbols(self) -> list[str]:
        return [r["symbol"] for r in self.query("select symbol from tickers where in_sp500 order by symbol")]

    def universe_symbols(self) -> list[str]:
        """Everything the screen ranks: S&P 500 + S&P 400 members."""
        rows = self.query("select symbol from tickers where in_sp500 or in_sp400 order by symbol")
        return [r["symbol"] for r in rows]

    def upsert_screens(self, rows: Sequence[dict]) -> int:
        return self._upsert("screens", rows, on_conflict="as_of,ticker")

    def latest_selected(self) -> list[str]:
        """Tickers selected by the most recent screen, best rank first."""
        rows = self.query(
            "select ticker from screens where selected and as_of = "
            "(select max(as_of) from screens where selected) order by rank"
        )
        return [r["ticker"] for r in rows]

    def has_documents(self, ticker: str) -> bool:
        return bool(self.query("select 1 from documents where ticker = %s limit 1", (ticker,)))

    def get_prices(self, ticker: str, start: date, before: date) -> list[dict]:
        """Daily bars with start <= date < before (strictly before the as-of date)."""
        return self.query(
            "select date, close, adj_close, volume from prices "
            "where ticker = %s and date >= %s and date < %s order by date",
            (ticker, start, before),
        )

    def get_macro(self, series_ids: Sequence[str], start: date, before: date) -> list[dict]:
        return self.query(
            "select series_id, date, value from macro_series "
            "where series_id = any(%s) and date >= %s and date < %s order by date",
            (list(series_ids), start, before),
        )

    def get_fundamentals(self, ticker: str, before: date) -> list[dict]:
        """Facts whose filing was public before the as-of date."""
        return self.query(
            "select concept, unit, period_start, period_end, value, form, filed from fundamentals "
            "where ticker = %s and filed < %s order by filed",
            (ticker, before),
        )

    def get_news_sentiment(self, ticker: str, start: date, before: date) -> list[dict]:
        return self.query(
            "select published_at, sentiment from documents "
            "where ticker = %s and source = 'news' and sentiment is not null "
            "and published_at >= %s and published_at < %s order by published_at",
            (ticker, start, before),
        )

    def fetch_unscored_news(self, limit: int = 200) -> list[dict]:
        return self.query(
            "select id, title, body from documents where source = 'news' and scored_at is null "
            "order by ingested_at limit %s",
            (limit,),
        )

    def get_document_meta(self, ids: Sequence[int]) -> dict[int, dict]:
        if not ids:
            return {}
        rows = self.query("select id, title, url from documents where id = any(%s)", (list(ids),))
        return {r["id"]: r for r in rows}

    def rpc(self, name: str, params: dict) -> list[dict]:
        """Call a set-returning SQL function with named arguments."""
        if name not in RPC_FUNCTIONS:
            raise ValueError(f"Unknown database function: {name}")
        from psycopg import sql

        args = {k: _vector(v) if k == "query_embedding" and not isinstance(v, str) else v
                for k, v in params.items()}
        stmt = sql.SQL("select * from {}({})").format(
            sql.Identifier(name),
            sql.SQL(", ").join(
                sql.SQL("{} => {}").format(sql.Identifier(k), sql.Placeholder(k)) for k in args
            ),
        )
        return self.query(stmt, args)

    # ------------------------------------------------------------ incremental refresh
    def price_marks(self, symbols: Sequence[str]) -> dict[str, dict]:
        """{symbol: {"first", "last", "adj_close"}} — stored range and the last stored adjusted close."""
        if not symbols:
            return {}
        rows = self.query(
            "with m as (select ticker, min(date) as first, max(date) as last from prices "
            "           where ticker = any(%s) group by ticker) "
            "select m.ticker, m.first, m.last, p.adj_close from m "
            "join prices p on p.ticker = m.ticker and p.date = m.last",
            (list(symbols),),
        )
        return {r["ticker"]: r for r in rows}

    def fundamentals_marks(self, symbols: Sequence[str]) -> dict[str, dict]:
        """{symbol: {"first", "last"}} — earliest and latest stored filing dates."""
        if not symbols:
            return {}
        rows = self.query(
            "select ticker, min(filed) as first, max(filed) as last from fundamentals "
            "where ticker = any(%s) group by ticker",
            (list(symbols),),
        )
        return {r["ticker"]: r for r in rows}

    # ------------------------------------------------------------ retention
    def prune(self, cutoffs: dict[str, date], focus_since: date, benchmark: str) -> dict[str, int]:
        """Delete what no module reads any more (see orchestration/retention.py for the windows).
        Chunks cited by a suggestion, and their documents, are always kept."""
        p = {**cutoffs, "focus_since": focus_since, "bench": benchmark}
        cited = ("select distinct substring(x from 7)::bigint as id from suggestions, unnest(sources) x "
                 "where x ~ '^chunk_[0-9]+$'")
        focus = ("select symbol from tickers where active or symbol = %(bench)s "
                 "union select ticker from screens where selected and as_of >= %(focus_since)s")
        stale_doc = ("((d.source = 'news' and d.published_at < %(news)s) "
                     " or (d.source = 'filing' and d.published_at < %(filings)s) "
                     f" or d.ticker not in ({focus}))")
        steps = {
            # Tickers that left the indexes, aren't on the watchlist and were never suggested:
            # cascades to their prices, fundamentals, documents, chunks and screens.
            "tickers": "delete from tickers t where not t.active and not t.in_sp500 and not t.in_sp400 "
                       "and t.symbol <> %(bench)s "
                       "and not exists (select 1 from suggestions s where s.ticker = t.symbol) "
                       "and not exists (select 1 from screens sc where sc.ticker = t.symbol and sc.selected "
                       "                and sc.as_of >= %(focus_since)s) "
                       f"and not exists (select 1 from chunks c where c.ticker = t.symbol and c.id in ({cited}))",
            "chunks": f"delete from chunks c using documents d where c.document_id = d.id and {stale_doc} "
                      f"and c.id not in ({cited})",
            "documents": f"delete from documents d where {stale_doc} and not exists "
                         f"(select 1 from chunks c where c.document_id = d.id)",
            # Once chunked (and, for news, scored) the full text is never read again.
            "document_bodies": "update documents set body = null where body is not null and processed_at is not null "
                               "and (source = 'filing' or scored_at is not null)",
            "prices": "delete from prices where date < %(prices)s",
            "fundamentals": "delete from fundamentals where filed < %(fundamentals)s",
            "macro_series": "delete from macro_series where date < %(macro)s",
            "screens": "delete from screens where as_of < %(screens)s",
            "tool_calls": "delete from tool_calls where created_at < %(logs)s",
            "ingestion_runs": "delete from ingestion_runs where started_at < %(logs)s",
        }
        out: dict[str, int] = {}
        with self._lock, self.conn.transaction():
            for name, stmt in steps.items():
                out[name] = self.execute(stmt, p)
        return out

    # ------------------------------------------------------------ website (read-only)
    def agent_runs(self, limit: int = 20) -> list[dict]:
        return self.query("select * from agent_runs order by id desc limit %s", (limit,))

    def latest_good_run(self) -> dict | None:
        rows = self.query("select * from agent_runs where status in ('ok', 'partial') order by id desc limit 1")
        return rows[0] if rows else None

    def ingestion_runs(self, limit: int = 40) -> list[dict]:
        return self.query(
            "select job, started_at, finished_at, status, counts, errors from ingestion_runs "
            "order by started_at desc limit %s",
            (limit,),
        )

    def suggestions_for_run(self, run_id: int) -> list[dict]:
        return self.query("select * from suggestions where run_id = %s order by ticker", (run_id,))

    def ticker_suggestions(self, ticker: str, limit: int = 30) -> list[dict]:
        return self.query("select * from suggestions where ticker = %s order by as_of desc limit %s",
                          (ticker, limit))

    def tickers(self) -> list[dict]:
        return self.query("select symbol, name, active from tickers where active order by symbol")

    def get_chunks(self, ids: Sequence[int]) -> list[dict]:
        if not ids:
            return []
        return self.query(
            "select id, document_id, ticker, source, doc_type, published_at, content from chunks "
            "where id = any(%s)",
            (sorted(set(ids)),),
        )

    # ------------------------------------------------------------ app API (read-only)
    APP_RUN_COLUMNS = "id, as_of, model, started_at, finished_at, status"  # never `error` (stack traces)

    def app_run(self, before_id: int | None = None) -> dict | None:
        """Latest good run, or the latest one before `before_id`."""
        rows = self.query(
            f"select {self.APP_RUN_COLUMNS} from agent_runs where status in ('ok', 'partial') "
            "and (%(before)s::bigint is null or id < %(before)s) order by id desc limit 1",
            {"before": before_id},
        )
        return rows[0] if rows else None

    def app_prices(self, tickers: Sequence[str], since: date) -> list[dict]:
        return self.query(
            "select ticker, date, close, adj_close from prices where ticker = any(%s) and date >= %s "
            "order by ticker, date",
            (list(tickers), since),
        )

    def app_citations(self, ids: Sequence[int]) -> list[dict]:
        """Only chunks that some suggestion actually cites, at most 20 per call; http(s) links only."""
        return self.query(
            "select c.id, c.ticker, c.source, c.doc_type, c.published_at, c.content, d.title, "
            "       case when d.url ~* '^https?://' then d.url end as url "
            "from chunks c join documents d on d.id = c.document_id "
            "where c.id = any(%s) "
            "  and exists (select 1 from suggestions s where ('chunk_' || c.id) = any(s.sources))",
            (list(ids)[:20],),
        )

    def app_latest_screen(self) -> dict:
        rows = self.query(
            "select as_of, ticker, rank, selected, metrics from screens "
            "where as_of = (select max(as_of) from screens where selected)"
        )
        return {"as_of": rows[0]["as_of"] if rows else None,
                "rows": [{k: r[k] for k in ("ticker", "rank", "selected", "metrics")} for r in rows]}
