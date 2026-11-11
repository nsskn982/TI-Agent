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

-- Retrieval functions are for the service role only.
revoke execute on function match_chunks(vector, timestamptz, int, text, text) from public, anon, authenticated;
revoke execute on function keyword_chunks(text, timestamptz, int, text, text) from public, anon, authenticated;
revoke execute on function set_sentiment(jsonb) from public, anon, authenticated;
