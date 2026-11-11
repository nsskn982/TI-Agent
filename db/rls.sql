-- Row level security. The service key (ingestion, agent, evaluation) bypasses RLS.
-- The app uses the anon key + Supabase Auth: only signed-in (invite-only) users
-- can read results. Only the service role can read raw data or write anything.

alter table tickers         enable row level security;
alter table prices          enable row level security;
alter table macro_series    enable row level security;
alter table documents       enable row level security;
alter table chunks          enable row level security;
alter table agent_runs      enable row level security;
alter table tool_calls      enable row level security;
alter table suggestions     enable row level security;
alter table portfolio_runs  enable row level security;
alter table performance     enable row level security;
alter table ingestion_runs  enable row level security;
alter table fundamentals    enable row level security;

drop policy if exists "authenticated read" on tickers;
create policy "authenticated read" on tickers        for select to authenticated using (true);

drop policy if exists "authenticated read" on prices;
create policy "authenticated read" on prices         for select to authenticated using (true);

drop policy if exists "authenticated read" on suggestions;
create policy "authenticated read" on suggestions    for select to authenticated using (true);

drop policy if exists "authenticated read" on portfolio_runs;
create policy "authenticated read" on portfolio_runs for select to authenticated using (true);

drop policy if exists "authenticated read" on performance;
create policy "authenticated read" on performance    for select to authenticated using (true);

-- Explicit grants. Projects created with "automatically expose new tables" turned off
-- don't give Supabase's API roles default privileges, so grant what each role needs.
grant usage on schema public to service_role, authenticated, anon;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;
grant select on tickers, prices, suggestions, portfolio_runs, performance to authenticated;

-- App users are viewers. RLS already blocks their writes (no write policies), but Supabase's
-- default privileges still grant the API roles INSERT/UPDATE/DELETE. Revoke them as a second
-- layer, so a future policy mistake can't open writes.
revoke insert, update, delete, truncate on all tables in schema public from anon, authenticated;
alter default privileges in schema public revoke insert, update, delete, truncate on tables from anon, authenticated;

-- Retrieval functions are for the service role only.
revoke execute on function match_chunks(vector, timestamptz, int, text, text) from public, anon, authenticated;
revoke execute on function keyword_chunks(text, timestamptz, int, text, text) from public, anon, authenticated;
revoke execute on function set_sentiment(jsonb) from public, anon, authenticated;

-- ---------------------------------------------------------------- app (Flutter) access
-- The app signs in with Supabase Auth and reads with the anon key, so everything below is
-- what a signed-in user can see. Turn OFF public sign-ups in Supabase (Authentication ->
-- Sign In / Providers -> "Allow new users to sign up") and invite users instead; otherwise
-- anyone could create an account and become `authenticated`.

-- Run summaries, without the error column (it can hold stack traces / local paths).
drop policy if exists "authenticated read" on agent_runs;
create policy "authenticated read" on agent_runs for select to authenticated using (true);
revoke select on agent_runs from authenticated;
grant select (id, as_of, model, started_at, finished_at, status) on agent_runs to authenticated;

-- Cited passages: only chunks that some suggestion actually cites, at most 20 per call.
-- SECURITY DEFINER reads chunks/documents (which stay closed to the app) on the caller's behalf.
create or replace function app_citations(ids bigint[])
returns table (id bigint, ticker text, source text, doc_type text, published_at timestamptz,
               content text, title text, url text)
language sql stable security definer set search_path = public as $$
    select c.id, c.ticker, c.source, c.doc_type, c.published_at, c.content, d.title,
           case when d.url ~* '^https?://' then d.url end
    from chunks c
    join documents d on d.id = c.document_id
    where c.id = any(ids[1:20])
      and exists (select 1 from suggestions s where ('chunk_' || c.id) = any(s.sources))
$$;
revoke execute on function app_citations(bigint[]) from public, anon;
grant execute on function app_citations(bigint[]) to authenticated, service_role;

-- S&P 500 screen: signed-in users see the ranking and why each pick made the list.
alter table screens enable row level security;
drop policy if exists "authenticated read" on screens;
create policy "authenticated read" on screens for select to authenticated using (true);
grant select on screens to authenticated;
grant all on screens to service_role;
