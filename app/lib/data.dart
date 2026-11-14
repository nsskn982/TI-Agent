import 'dart:convert';

import 'models.dart';
import 'session.dart';

/// Everything the app reads. ApiDataSource reads the laptop's server as the signed-in
/// user; tests use an in-memory fake.
abstract class DataSource {
  Future<AgentRun?> latestRun();
  Future<AgentRun?> previousRun(int beforeId);
  Future<List<Suggestion>> suggestionsForRun(int runId);
  Future<List<Suggestion>> tickerHistory(String ticker);
  Future<List<PricePoint>> prices(String ticker, {int days = 365});
  Future<Map<int, Citation>> citations(List<int> ids);

  /// The latest weekly S&P 500 screen (empty before the first screen has run).
  Future<ScreenResult> latestScreen();

  /// Latest daily close and recent move for each ticker (last ~2 weeks of rows).
  Future<Map<String, Quote>> latestQuotes(List<String> tickers);
}

/// Reads the laptop's JSON API (web/dashboard/api.py) with the signed-in user's token.
class ApiDataSource implements DataSource {
  ApiDataSource(this.session);

  final Session session;

  Future<Map<String, dynamic>> _get(String path, [Map<String, String>? query]) async {
    final r = await session.client
        .get(session.uri(path, query), headers: {'Authorization': 'Bearer ${session.token ?? ''}'});
    if (r.statusCode == 401) {
      await session.signOut(); // token expired or revoked: back to the login screen
      throw const ApiException('Signed out. Please sign in again.');
    }
    if (r.statusCode != 200) throw ApiException('Server error (HTTP ${r.statusCode}).');
    return Map<String, dynamic>.from(jsonDecode(r.body) as Map);
  }

  static List<Map<String, dynamic>> _rows(Map<String, dynamic> body) =>
      [for (final r in (body['rows'] as List? ?? const [])) Map<String, dynamic>.from(r as Map)];

  static AgentRun? _run(Map<String, dynamic> body) {
    final run = body['run'];
    return run == null ? null : AgentRun.fromJson(Map<String, dynamic>.from(run as Map));
  }

  @override
  Future<AgentRun?> latestRun() async => _run(await _get('/api/runs/latest'));

  @override
  Future<AgentRun?> previousRun(int beforeId) async => _run(await _get('/api/runs/latest', {'before': '$beforeId'}));

  @override
  Future<List<Suggestion>> suggestionsForRun(int runId) async =>
      [for (final r in _rows(await _get('/api/runs/$runId/suggestions'))) Suggestion.fromJson(r)];

  @override
  Future<List<Suggestion>> tickerHistory(String ticker) async => [
        for (final r in _rows(await _get('/api/tickers/${Uri.encodeComponent(ticker)}/suggestions')))
          Suggestion.fromJson(r),
      ];

  @override
  Future<List<PricePoint>> prices(String ticker, {int days = 365}) async =>
      _rows(await _get('/api/prices', {'tickers': ticker, 'days': '$days'}))
          .map(PricePoint.fromJson)
          .whereType<PricePoint>()
          .toList();

  @override
  Future<Map<int, Citation>> citations(List<int> ids) async {
    final out = <int, Citation>{};
    final unique = ids.toSet().toList();
    // The API returns at most 20 rows per call, and only chunks some suggestion cites.
    for (var i = 0; i < unique.length; i += 20) {
      final batch = unique.sublist(i, i + 20 > unique.length ? unique.length : i + 20);
      for (final r in _rows(await _get('/api/citations', {'ids': batch.join(',')}))) {
        final c = Citation.fromJson(r);
        out[c.id] = c;
      }
    }
    return out;
  }

  @override
  Future<Map<String, Quote>> latestQuotes(List<String> tickers) async {
    if (tickers.isEmpty) return {};
    final rows = _rows(await _get('/api/prices', {'tickers': tickers.join(','), 'days': '16'}));
    final by = <String, List<PricePoint>>{};
    for (final r in rows) {
      final p = PricePoint.fromJson(r);
      if (p != null) (by[r['ticker'].toString()] ??= []).add(p);
    }
    return {for (final e in by.entries) if (Quote.fromSeries(e.value) case final q?) e.key: q};
  }

  @override
  Future<ScreenResult> latestScreen() async {
    final body = await _get('/api/screen/latest');
    if (body['as_of'] == null) return const ScreenResult();
    final rows = _rows(body);
    return ScreenResult(
      asOf: body['as_of'].toString(),
      screened: rows.length,
      picks: {
        for (final r in rows)
          if (r['selected'] == true && r['rank'] != null) r['ticker'].toString(): ScreenPick.fromJson(r),
      },
    );
  }
}

class ApiException implements Exception {
  const ApiException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// One ticker's two views for the week, plus its place in the S&P 500 screen.
class TickerViews {
  const TickerViews(this.ticker, {this.medium, this.long, this.pick});

  final String ticker;
  final Suggestion? medium;
  final Suggestion? long;
  final ScreenPick? pick;

  Stance get lead => (medium ?? long)?.stance ?? Stance.neutral;
}

class HomeStats {
  const HomeStats(
      {this.tickers = 0, this.views = 0, this.bullish = 0, this.sources = 0, this.changed = 0, this.screened = 0});

  final int tickers, views, bullish, sources, changed;
  final int screened; // S&P 500 stocks screened to pick these (0 before the first screen)
}

class HomeData {
  const HomeData(
      {this.run, this.cards = const [], this.citations = const {}, this.stats = const HomeStats(), this.quotes = const {}});

  final AgentRun? run;
  final List<TickerViews> cards;
  final Map<int, Citation> citations;
  final HomeStats stats;
  final Map<String, Quote> quotes; // latest daily close per ticker
}

/// Tags each view as new, changed or unchanged against the previous run's stances.
void markChanges(List<Suggestion> current, Map<String, Stance> previous) {
  for (final s in current) {
    final before = previous[s.key];
    s.previousStance = before;
    s.change = before == null ? Change.isNew : (before == s.stance ? Change.unchanged : Change.changed);
  }
}

/// One card per ticker: best screen rank first, then alphabetical for anything unranked.
List<TickerViews> groupByTicker(List<Suggestion> rows, [Map<String, ScreenPick> picks = const {}]) {
  final by = <String, Map<String, Suggestion>>{};
  for (final s in rows) {
    (by[s.ticker] ??= {})[s.horizon] = s;
  }
  final tickers = by.keys.toList()
    ..sort((a, b) {
      final ra = picks[a]?.rank ?? 1 << 30, rb = picks[b]?.rank ?? 1 << 30;
      return ra != rb ? ra.compareTo(rb) : a.compareTo(b);
    });
  return [
    for (final t in tickers) TickerViews(t, medium: by[t]!['medium'], long: by[t]!['long'], pick: picks[t]),
  ];
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
  ScreenResult screen;
  try {
    screen = await ds.latestScreen();
  } catch (_) {
    screen = const ScreenResult(); // no screen yet (or table not created): plain alphabetical list
  }
  final cards = groupByTicker(rows, screen.picks);
  Map<String, Quote> quotes;
  try {
    quotes = await ds.latestQuotes([for (final c in cards) c.ticker]);
  } catch (_) {
    quotes = const {}; // prices are a bonus; never block the suggestions
  }
  return HomeData(
    run: run,
    cards: cards,
    citations: cites,
    quotes: quotes,
    stats: HomeStats(
      tickers: cards.length,
      views: rows.length,
      bullish: rows.where((s) => s.stance == Stance.bullish).length,
      sources: cites.length,
      changed: rows.where((s) => s.change == Change.isNew || s.change == Change.changed).length,
      screened: screen.screened,
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
