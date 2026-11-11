import 'package:supabase_flutter/supabase_flutter.dart';

import 'models.dart';

/// Everything the app reads. The Supabase implementation runs under row-level security
/// as the signed-in user; tests use an in-memory fake.
abstract class DataSource {
  Future<AgentRun?> latestRun();
  Future<AgentRun?> previousRun(int beforeId);
  Future<List<Suggestion>> suggestionsForRun(int runId);
  Future<List<Suggestion>> tickerHistory(String ticker);
  Future<List<PricePoint>> prices(String ticker, {int days = 365});
  Future<Map<int, Citation>> citations(List<int> ids);
}

class SupabaseDataSource implements DataSource {
  SupabaseDataSource(this.db);

  final SupabaseClient db;

  // Only these columns of agent_runs are granted to the app (not `error`).
  static const _runColumns = 'id,as_of,status,model,started_at';
  static const _good = ['ok', 'partial'];

  @override
  Future<AgentRun?> latestRun() async {
    final rows = await db
        .from('agent_runs')
        .select(_runColumns)
        .inFilter('status', _good)
        .order('id', ascending: false)
        .limit(1);
    return rows.isEmpty ? null : AgentRun.fromJson(rows.first);
  }

  @override
  Future<AgentRun?> previousRun(int beforeId) async {
    final rows = await db
        .from('agent_runs')
        .select(_runColumns)
        .inFilter('status', _good)
        .lt('id', beforeId)
        .order('id', ascending: false)
        .limit(1);
    return rows.isEmpty ? null : AgentRun.fromJson(rows.first);
  }

  @override
  Future<List<Suggestion>> suggestionsForRun(int runId) async {
    final rows = await db.from('suggestions').select().eq('run_id', runId);
    return [for (final r in rows) Suggestion.fromJson(r)];
  }

  @override
  Future<List<Suggestion>> tickerHistory(String ticker) async {
    final rows = await db
        .from('suggestions')
        .select()
        .eq('ticker', ticker)
        .order('as_of', ascending: false)
        .limit(30);
    return [for (final r in rows) Suggestion.fromJson(r)];
  }

  @override
  Future<List<PricePoint>> prices(String ticker, {int days = 365}) async {
    final since = DateTime.now().subtract(Duration(days: days)).toIso8601String().substring(0, 10);
    final rows = await db
        .from('prices')
        .select('date,close,adj_close')
        .eq('ticker', ticker)
        .gte('date', since)
        .order('date', ascending: true);
    return rows.map(PricePoint.fromJson).whereType<PricePoint>().toList();
  }

  @override
  Future<Map<int, Citation>> citations(List<int> ids) async {
    final out = <int, Citation>{};
    final unique = ids.toSet().toList();
    // app_citations() returns at most 20 rows per call, and only chunks some suggestion cites.
    for (var i = 0; i < unique.length; i += 20) {
      final batch = unique.sublist(i, i + 20 > unique.length ? unique.length : i + 20);
      final rows = await db.rpc('app_citations', params: {'ids': batch}) as List<dynamic>;
      for (final r in rows) {
        final c = Citation.fromJson(Map<String, dynamic>.from(r as Map));
        out[c.id] = c;
      }
    }
    return out;
  }
}

/// One ticker's two views for the week.
class TickerViews {
  const TickerViews(this.ticker, {this.medium, this.long});

  final String ticker;
  final Suggestion? medium;
  final Suggestion? long;

  Stance get lead => (medium ?? long)?.stance ?? Stance.neutral;
}

class HomeStats {
  const HomeStats({this.tickers = 0, this.views = 0, this.bullish = 0, this.sources = 0, this.changed = 0});

  final int tickers, views, bullish, sources, changed;
}

class HomeData {
  const HomeData({this.run, this.cards = const [], this.citations = const {}, this.stats = const HomeStats()});

  final AgentRun? run;
  final List<TickerViews> cards;
  final Map<int, Citation> citations;
  final HomeStats stats;
}

/// Tags each view as new, changed or unchanged against the previous run's stances.
void markChanges(List<Suggestion> current, Map<String, Stance> previous) {
  for (final s in current) {
    final before = previous[s.key];
    s.previousStance = before;
    s.change = before == null ? Change.isNew : (before == s.stance ? Change.unchanged : Change.changed);
  }
}

List<TickerViews> groupByTicker(List<Suggestion> rows) {
  final by = <String, Map<String, Suggestion>>{};
  for (final s in rows) {
    (by[s.ticker] ??= {})[s.horizon] = s;
  }
  final tickers = by.keys.toList()..sort();
  return [for (final t in tickers) TickerViews(t, medium: by[t]!['medium'], long: by[t]!['long'])];
}

Future<HomeData> loadHome(DataSource ds) async {
  final run = await ds.latestRun();
  if (run == null) return const HomeData();
  final rows = await ds.suggestionsForRun(run.id);
  final prev = await ds.previousRun(run.id);
  final before = prev == null
      ? <String, Stance>{}
      : {for (final s in await ds.suggestionsForRun(prev.id)) s.key: s.stance};
  markChanges(rows, before);
  final cites = await ds.citations([for (final s in rows) ...s.chunkIds]);
  final cards = groupByTicker(rows);
  return HomeData(
    run: run,
    cards: cards,
    citations: cites,
    stats: HomeStats(
      tickers: cards.length,
      views: rows.length,
      bullish: rows.where((s) => s.stance == Stance.bullish).length,
      sources: cites.length,
      changed: rows.where((s) => s.change == Change.isNew || s.change == Change.changed).length,
    ),
  );
}

class IndexedPoint {
  const IndexedPoint(this.date, this.value, this.price);

  final DateTime date;
  final double value; // start of window = 100
  final double price;
}

/// Rebases a price series to 100 at its first point, so two tickers share one axis.
List<IndexedPoint> rebase(List<PricePoint> pts) {
  if (pts.isEmpty) return const [];
  final base = pts.first.price;
  return [for (final p in pts) IndexedPoint(p.date, p.price / base * 100, p.price)];
}
