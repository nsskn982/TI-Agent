import 'package:ti_agent/data.dart';
import 'package:ti_agent/models.dart';

Map<String, dynamic> sugJson(String ticker, String horizon, String stance,
        {int run = 2, List<String> sources = const ['chunk_10'], String thesis = 'Revenue grew 15.1% year on year.'}) =>
    {
      'id': ticker.hashCode ^ horizon.hashCode ^ run,
      'run_id': run,
      'ticker': ticker,
      'horizon': horizon,
      'stance': stance,
      'thesis': thesis,
      'risks': ['Valuation', 'Regulation'],
      'sources': sources,
      'confidence': 0.6,
      'as_of': '2026-11-11',
    };

/// In-memory stand-in for Supabase.
class FakeData implements DataSource {
  FakeData({this.previous = const []});

  final List<Map<String, dynamic>> previous;
  int citationCalls = 0;

  final current = [
    sugJson('MSFT', 'medium', 'bearish', sources: ['chunk_10', 'chunk_99']),
    sugJson('AAPL', 'medium', 'bullish'),
    sugJson('AAPL', 'long', 'neutral'),
  ];

  @override
  Future<AgentRun?> latestRun() async => const AgentRun(id: 2, asOf: '2026-11-11', status: 'ok');

  @override
  Future<AgentRun?> previousRun(int beforeId) async =>
      previous.isEmpty ? null : const AgentRun(id: 1, asOf: '2026-11-04', status: 'ok');

  @override
  Future<List<Suggestion>> suggestionsForRun(int runId) async =>
      [for (final j in runId == 2 ? current : previous) Suggestion.fromJson(j)];

  @override
  Future<List<Suggestion>> tickerHistory(String ticker) async =>
      [for (final j in current.where((j) => j['ticker'] == ticker)) Suggestion.fromJson(j)];

  @override
  Future<List<PricePoint>> prices(String ticker, {int days = 365}) async => [
        for (var i = 0; i < 30; i++) PricePoint(DateTime(2026, 1, 1).add(Duration(days: i)), (ticker == 'SPY' ? 500 : 100) + i.toDouble()),
      ];

  @override
  Future<Map<int, Citation>> citations(List<int> ids) async {
    citationCalls++;
    return {
      if (ids.contains(10))
        10: const Citation(
          id: 10,
          ticker: 'AAPL',
          source: 'filing',
          docType: '10-K',
          publishedAt: '2026-11-03T20:00:00+00:00',
          content: 'Greater China net sales decreased...',
          title: 'AAPL 10-K filed 2026-11-03',
          url: 'https://www.sec.gov/x.htm',
        ),
    };
  }
}
