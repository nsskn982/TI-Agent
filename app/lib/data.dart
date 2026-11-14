import 'models.dart';

/// Everything the app reads. BundleDataSource reads the decrypted data file from GitHub
/// Pages; tests use an in-memory fake.
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

/// Reads the decrypted data file (see vault.dart and orchestration/export_app.py).
class BundleDataSource implements DataSource {
  BundleDataSource(this.d);

  final Map<String, dynamic> d;

  List<Map<String, dynamic>> _list(Object? v) =>
      [for (final r in (v as List? ?? const [])) Map<String, dynamic>.from(r as Map)];

  List<AgentRun> get _runs => [for (final r in _list(d['runs'])) AgentRun.fromJson(r)];

  @override
  Future<AgentRun?> latestRun() async => _runs.isEmpty ? null : _runs.first;

  @override
  Future<AgentRun?> previousRun(int beforeId) async {
    final older = _runs.where((r) => r.id < beforeId).toList()..sort((a, b) => b.id.compareTo(a.id));
    return older.isEmpty ? null : older.first;
  }

  @override
  Future<List<Suggestion>> suggestionsForRun(int runId) async =>
      [for (final r in _list((d['suggestions'] as Map?)?['$runId'])) Suggestion.fromJson(r)];

  @override
  Future<List<Suggestion>> tickerHistory(String ticker) async =>
      [for (final r in _list((d['history'] as Map?)?[ticker])) Suggestion.fromJson(r)];

  List<PricePoint> _prices(String ticker, int days) {
    final since = DateTime.now().subtract(Duration(days: days)).toIso8601String().substring(0, 10);
    final rows = (d['prices'] as Map?)?[ticker] as List? ?? const [];
    return [
      for (final r in rows)
        if ((r as List)[0].toString().compareTo(since) >= 0)
          if (PricePoint.fromJson({'date': r[0], 'close': r[1], 'adj_close': r[2]}) case final p?) p,
    ];
  }

  @override
  Future<List<PricePoint>> prices(String ticker, {int days = 365}) async => _prices(ticker, days);

  @override
  Future<Map<int, Citation>> citations(List<int> ids) async {
    final all = (d['citations'] as Map?) ?? const {};
    return {
      for (final id in ids.toSet())
        if (all['$id'] != null) id: Citation.fromJson(Map<String, dynamic>.from(all['$id'] as Map)),
    };
  }

  @override
  Future<Map<String, Quote>> latestQuotes(List<String> tickers) async => {
        for (final t in tickers)
          if (Quote.fromSeries(_prices(t, 16)) case final q?) t: q,
      };

  @override
  Future<ScreenResult> latestScreen() async {
    final s = Map<String, dynamic>.from((d['screen'] as Map?) ?? const {});
    if (s['as_of'] == null) return const ScreenResult();
    return ScreenResult(
      asOf: s['as_of'].toString(),
      screened: (s['screened'] as num?)?.toInt() ?? 0,
      picks: {for (final r in _list(s['picks'])) r['ticker'].toString(): ScreenPick.fromJson(r)},
    );
  }
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
