-- TI Agent schema (M3). Run in the Supabase SQL editor, then run rls.sql.
-- Idempotent: safe to re-run.

create extension if not exists vector;

-- ---------------------------------------------------------------- reference
create table if not exists tickers (
    symbol      text primary key,
    name        text,
    cik         bigint,
    active      boolean not null default true,
    added_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------- market data
create table if not exists prices (
    ticker      text not null references tickers(symbol) on delete cascade,
    date        date not null,
    open        double precision,
    high        double precision,
    low         double precision,
    close       double precision,
    adj_close   double precision,
    volume      bigint,
    primary key (ticker, date)
);

create table if not exists macro_series (
    series_id   text not null,
    date        date not null,
    value       double precision not null,
    primary key (series_id, date)
);

-- Phase 2: as-reported XBRL facts from SEC companyfacts. One row per fact per filing,
-- so the quant engine can rebuild exactly what was known on any as-of date.
-- Instant facts (balance sheet) store period_start = period_end.
create table if not exists fundamentals (
    ticker          text not null references tickers(symbol) on delete cascade,
    concept         text not null,           -- e.g. us-gaap:Revenues, dei:EntityCommonStockSharesOutstanding
    unit            text not null,
    period_start    date not null,
    period_end      date not null,
    value           double precision not null,
    form            text,
    fp              text,
    fy              int,
    filed           date not null,
    accn            text not null,
    primary key (ticker, concept, unit, period_start, period_end, accn)
);
create index if not exists fundamentals_ticker_filed_idx on fundamentals (ticker, filed);

-- ---------------------------------------------------------------- text corpus
create table if not exists documents (
    id              bigint generated always as identity primary key,
    ticker          text not null references tickers(symbol) on delete cascade,
    source          text not null check (source in ('news', 'filing')),
    source_id       text not null,           -- e.g. finnhub:123, edgar:0000320193-24-000123
    doc_type        text,                    -- publisher for news, form type (10-K ...) for filings
    title           text,
    url             text,
    published_at    timestamptz not null,
    body            text,
    meta            jsonb not null default '{}'::jsonb,
    ingested_at     timestamptz not null default now(),
    processed_at    timestamptz,
    process_error   text,
    unique (ticker, source, source_id)
);
-- Phase 2: news sentiment (FinBERT). `add column if not exists` upgrades Phase 1 installs.
alter table documents add column if not exists sentiment double precision;   -- p(pos) - p(neg), -1..1
alter table documents add column if not exists sentiment_label text;
alter table documents add column if not exists scored_at timestamptz;
create index if not exists documents_unscored_idx
    on documents (ingested_at) where source = 'news' and scored_at is null;
create index if not exists documents_unprocessed_idx
    on documents (ingested_at) where processed_at is null and process_error is null;
create index if not exists documents_ticker_published_idx on documents (ticker, published_at desc);

create table if not exists chunks (
    id              bigint generated always as identity primary key,
    document_id     bigint not null references documents(id) on delete cascade,
    ticker          text not null,
    source          text not null,
    doc_type        text,
    published_at    timestamptz not null,   -- denormalised for no-lookahead filtering
    chunk_index     int not null,
    content         text not null,
    embedding       vector(384) not null,
    tsv             tsvector generated always as (to_tsvector('english', content)) stored,
    unique (document_id, chunk_index)
);
create index if not exists chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);
create index if not exists chunks_tsv_idx on chunks using gin (tsv);
create index if not exists chunks_ticker_published_idx on chunks (ticker, published_at desc);

-- ---------------------------------------------------------------- agent output
create table if not exists agent_runs (
    id              bigint generated always as identity primary key,
    as_of           date not null,
    model           text,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    status          text not null default 'running' check (status in ('running', 'ok', 'error')),
    error           text
);

-- Phase 3: allow 'partial' (some tickers failed). Re-created so existing installs pick it up.
alter table agent_runs drop constraint if exists agent_runs_status_check;
alter table agent_runs add constraint agent_runs_status_check
    check (status in ('running', 'ok', 'partial', 'error'));

create table if not exists tool_calls (
    id              bigint generated always as identity primary key,
    run_id          bigint not null references agent_runs(id) on delete cascade,
    ticker          text,
    step            int not null,
    tool            text not null,
    arguments       jsonb,
    result_summary  text,
    duration_ms     int,
    created_at      timestamptz not null default now()
);

create table if not exists suggestions (
    id              bigint generated always as identity primary key,
    run_id          bigint references agent_runs(id) on delete set null,
    ticker          text not null references tickers(symbol),
    horizon         text not null check (horizon in ('medium', 'long')),
    stance          text not null check (stance in ('bullish', 'neutral', 'bearish')),
    thesis          text not null,
    risks           jsonb not null default '[]'::jsonb,
    sources         text[] not null default '{}',
    confidence      double precision not null check (confidence between 0 and 1),
    as_of           date not null,
    model           text,
    created_at      timestamptz not null default now(),
    unique (ticker, horizon, as_of)
);

create table if not exists portfolio_runs (
    id              bigint generated always as identity primary key,
    as_of           date not null,
    method          text not null,           -- 'mean_variance', 'qaoa', 'brute_force', ...
    weights         jsonb not null,           -- {"AAPL": 0.25, ...}
    objective       double precision,
    runtime_ms      int,
    params          jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);

create table if not exists performance (
    suggestion_id     bigint not null references suggestions(id) on delete cascade,
    horizon_days      int not null,           -- 21, 63, 252 trading days
    ticker_return     double precision,
    benchmark_return  double precision,
    excess_return     double precision,
    hit               boolean,
    evaluated_at      timestamptz not null default now(),
    primary key (suggestion_id, horizon_days)
);

-- ---------------------------------------------------------------- ops log
create table if not exists ingestion_runs (
    id              bigint generated always as identity primary key,
    job             text not null,            -- 'ingestion' | 'processing'
    started_at      timestamptz not null,
    finished_at     timestamptz not null default now(),
    status          text not null check (status in ('ok', 'partial', 'error')),
    counts          jsonb not null default '{}'::jsonb,
    errors          jsonb not null default '[]'::jsonb
);

-- ---------------------------------------------------------------- retrieval
-- Vector search that never looks past the as-of date.
-- HNSW applies WHERE filters *after* the index scan, so a ticker-filtered query
-- could silently return fewer than match_count rows. Ticker-filtered queries
-- therefore use an exact scan (per-ticker corpora are small); unfiltered ones
-- use the index with a wider ef_search.
create or replace function match_chunks(
    query_embedding vector(384),
    as_of           timestamptz,
    match_count     int default 10,
    filter_ticker   text default null,
    filter_source   text default null
)
returns table (
    id bigint, document_id bigint, ticker text, source text, doc_type text,
    published_at timestamptz, content text, similarity double precision
)
language plpgsql stable
as $$
#variable_conflict use_column
begin
    if filter_ticker is not null then
        return query
        select c.id, c.document_id, c.ticker, c.source, c.doc_type,
               c.published_at, c.content,
               1 - (c.embedding <=> query_embedding) as similarity
        from chunks c
        where c.ticker = filter_ticker
          and c.published_at < as_of
          and (filter_source is null or c.source = filter_source)
        order by (c.embedding <=> query_embedding) + 0   -- "+ 0" forces exact ordering, not HNSW
        limit match_count;
    else
        perform set_config('hnsw.ef_search', greatest(100, match_count * 4)::text, true);
        return query
        select c.id, c.document_id, c.ticker, c.source, c.doc_type,
               c.published_at, c.content,
               1 - (c.embedding <=> query_embedding) as similarity
        from chunks c
        where c.published_at < as_of
          and (filter_source is null or c.source = filter_source)
        order by c.embedding <=> query_embedding
        limit match_count;
    end if;
end;
$$;

-- Keyword side of hybrid search (fused with match_chunks via RRF in M5).
-- Natural-language questions rarely contain *all* terms of a chunk, so the
-- query's lexemes are OR-ed together and ranked by cover density.
drop function if exists keyword_chunks(text, timestamptz, int, text);
create or replace function keyword_chunks(
    query_text      text,
    as_of           timestamptz,
    match_count     int default 10,
    filter_ticker   text default null,
    filter_source   text default null
)
returns table (
    id bigint, document_id bigint, ticker text, source text, doc_type text,
    published_at timestamptz, content text, rank real
)
language sql stable
as $$
    with q as (
        select to_tsquery('simple', string_agg(quote_literal(lex), ' | ')) as q
        from unnest(tsvector_to_array(to_tsvector('english', query_text))) as lex
    )
    select c.id, c.document_id, c.ticker, c.source, c.doc_type,
           c.published_at, c.content,
           ts_rank_cd(c.tsv, q.q) as rank
    from chunks c, q
    where q.q is not null
      and c.tsv @@ q.q
      and c.published_at < as_of
      and (filter_ticker is null or c.ticker = filter_ticker)
      and (filter_source is null or c.source = filter_source)
    order by rank desc
    limit match_count;
$$;

-- Bulk-write FinBERT scores: [{"id": 1, "sentiment": 0.4, "label": "positive"}, ...]
create or replace function set_sentiment(payload jsonb)
returns int
language sql
as $$
    with u as (
        update documents d
        set sentiment = (x->>'sentiment')::double precision,
            sentiment_label = x->>'label',
            scored_at = now()
        from jsonb_array_elements(payload) x
        where d.id = (x->>'id')::bigint
        returning 1
    )
    select count(*)::int from u;
$$;

-- Realtime feed for the app (M9).
do $$
begin
    if not exists (
        select 1 from pg_publication_tables
        where pubname = 'supabase_realtime' and tablename = 'suggestions'
    ) then
        alter publication supabase_realtime add table suggestions;
    end if;
end $$;

-- ---------------------------------------------------------------- S&P 500 screen (weekly)
-- The whole S&P 500 is screened cheaply (prices + SEC fundamentals). Only the top N
-- ("selected") get news, filings, embeddings and LLM suggestions.
alter table tickers add column if not exists in_sp500 boolean not null default false;
alter table tickers add column if not exists sector   text;

create table if not exists screens (
    as_of           date not null,
    ticker          text not null references tickers(symbol) on delete cascade,
    rank            int,                         -- 1 = best; null = failed quality or not enough data
    score           double precision,
    quality_pass    boolean not null,
    selected        boolean not null default false,  -- in the top N handed to the agent
    metrics         jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    primary key (as_of, ticker)
);
create index if not exists screens_selected_idx on screens (as_of desc, rank) where selected;
