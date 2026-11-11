import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:ti_agent/config.dart';
import 'package:ti_agent/data.dart';
import 'package:ti_agent/models.dart';
import 'package:ti_agent/screens/compare_screen.dart';
import 'package:ti_agent/widgets/contact.dart';

import 'fake_data.dart';

String _jwt(Map<String, dynamic> payload) =>
    'e30.${base64Url.encode(utf8.encode(jsonEncode(payload))).replaceAll('=', '')}.sig';

void main() {
  group('config', () {
    test('refuses a service_role JWT or secret key, accepts the anon key', () {
      const url = 'https://abc.supabase.co';
      expect(AppConfig.checkKey(url, _jwt({'role': 'service_role'})), contains('secret key'));
      expect(AppConfig.checkKey(url, 'sb_secret_abc123'), contains('secret key'));
      expect(AppConfig.checkKey(url, _jwt({'role': 'anon'})), isNull);
      expect(AppConfig.checkKey(url, 'sb_publishable_abc123'), isNull);
      expect(AppConfig.checkKey('', 'x'), contains('Missing'));
      expect(AppConfig.checkKey('http://abc.supabase.co', 'x'), contains('https'));
    });
  });

  group('models', () {
    test('parses a suggestion row and its citation ids', () {
      final s = Suggestion.fromJson(sugJson('AAPL', 'long', 'bearish', sources: ['chunk_1', 'evil', 'chunk_22']));
      expect(s.stance, Stance.bearish);
      expect(s.horizonLabel, '6–24 months');
      expect(s.chunkIds, [1, 22]);
      expect(s.risks, ['Valuation', 'Regulation']);
    });

    test('only http(s) links are kept', () {
      expect(safeUrl('javascript:alert(1)'), isNull);
      expect(safeUrl('file:///etc/passwd'), isNull);
      expect(safeUrl('https://www.sec.gov/a'), 'https://www.sec.gov/a');
      expect(Citation.fromJson({
        'id': 1, 'ticker': 'A', 'source': 'news', 'published_at': '2026-11-05', 'content': 'x', 'url': 'javascript:x',
      }).url, isNull);
    });

    test('price rows prefer adjusted close and drop empty rows', () {
      expect(PricePoint.fromJson({'date': '2026-01-02', 'close': 10, 'adj_close': 9.5})!.price, 9.5);
      expect(PricePoint.fromJson({'date': '2026-01-02', 'close': null, 'adj_close': null}), isNull);
    });
  });

  group('home data', () {
    test('groups by ticker in order and counts stats', () async {
      final home = await loadHome(FakeData());
      expect(home.cards.map((c) => c.ticker), ['AAPL', 'MSFT']);
      expect(home.cards.first.medium!.stance, Stance.bullish);
      expect(home.stats.views, 3);
      expect(home.stats.bullish, 1);
      expect(home.stats.sources, 1); // chunk_99 is not returned
      expect(home.stats.changed, 3); // no previous run: all new
    });

    test('marks new, changed and unchanged against the previous run', () async {
      final home = await loadHome(FakeData(previous: [
        sugJson('AAPL', 'medium', 'bullish', run: 1),
        sugJson('AAPL', 'long', 'bullish', run: 1),
      ]));
      final aapl = home.cards.first;
      expect(aapl.medium!.change, Change.unchanged);
      expect(aapl.long!.change, Change.changed);
      expect(aapl.long!.previousStance, Stance.bullish);
      expect(home.cards.last.medium!.change, Change.isNew);
    });

    test('orders cards by screen rank and reports how many were screened', () async {
      final home = await loadHome(FakeData(
        screen: const ScreenResult(asOf: '2026-11-14', screened: 503, picks: {
          'MSFT': ScreenPick(ticker: 'MSFT', rank: 1, metrics: {'mom_12_1': 0.62, 'sector': 'Information Technology'}),
          'AAPL': ScreenPick(ticker: 'AAPL', rank: 7),
        }),
      ));
      expect(home.cards.map((c) => c.ticker), ['MSFT', 'AAPL']);
      expect(home.cards.first.pick!.metric('mom_12_1'), 0.62);
      expect(home.stats.screened, 503);
    });

    test('a failing screen lookup still shows the suggestions', () async {
      final home = await loadHome(_BrokenScreen());
      expect(home.cards.map((c) => c.ticker), ['AAPL', 'MSFT']);
      expect(home.stats.screened, 0);
    });

    test('compare sorting puts missing values last in both directions', () {
      TickerViews card(String t, double? pe) =>
          TickerViews(t, pick: ScreenPick(ticker: t, rank: 1, metrics: {if (pe != null) 'pe_ttm': pe}));
      final cards = [card('A', 20), card('B', null), card('C', 35)];
      final pe = compareColumns.firstWhere((c) => c.label == 'P/E');
      expect(sortCards(cards, const {}, pe, true).map((c) => c.ticker), ['A', 'C', 'B']);
      expect(sortCards(cards, const {}, pe, false).map((c) => c.ticker), ['C', 'A', 'B']);
    });

    test('daily quote moves', () {
      final q = Quote.fromSeries([
        for (var i = 0; i < 7; i++) PricePoint(DateTime(2026, 11, 2 + i), 100.0 + i),
      ])!;
      expect(q.close, 106);
      expect(q.dayChange, closeTo(106 / 105 - 1, 1e-9));
      expect(q.weekChange, closeTo(106 / 101 - 1, 1e-9));
    });

    test('percent formatting', () {
      expect(fmtPct(0.624), '+62%');
      expect(fmtPct(-0.04), '-4%');
      expect(fmtPct(0.25, signed: false), '25%');
      expect(fmtPct(null), '–');
    });

    test('rebase starts at 100', () {
      final r = rebase([PricePoint(DateTime(2026), 50), PricePoint(DateTime(2026, 1, 2), 55)]);
      expect(r.map((p) => p.value), [100, closeTo(110, 1e-9)]);
    });
  });

  test('contact links hide empty or unsafe URLs', () {
    expect(contactLinks(linkedin: '', github: 'https://github.com/nsskn982').map((l) => l.label), ['GitHub']);
    expect(contactLinks(linkedin: 'https://www.linkedin.com/in/x', github: 'javascript:x').map((l) => l.label),
        ['LinkedIn']);
  });
}

class _BrokenScreen extends FakeData {
  @override
  Future<ScreenResult> latestScreen() async => throw Exception('relation "screens" does not exist');
}
