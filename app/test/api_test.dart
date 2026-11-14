import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ti_agent/data.dart';
import 'package:ti_agent/session.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('signs in, sends the bearer token, and a 401 signs out', () async {
    final seen = <http.Request>[];
    var revoked = false;
    final client = MockClient((req) async {
      seen.add(req);
      if (req.url.path == '/api/login') {
        final body = jsonDecode(req.body) as Map;
        return body['password'] == 'right'
            ? http.Response(jsonEncode({'token': 'tok', 'expires_in': 3600}), 200)
            : http.Response(jsonEncode({'error': 'Invalid login credentials.'}), 401);
      }
      if (revoked || req.headers['Authorization'] != 'Bearer tok') return http.Response('{}', 401);
      return http.Response(jsonEncode({'run': {'id': 7, 'as_of': '2026-11-14', 'status': 'ok', 'model': 'm'}}), 200);
    });

    final session = Session('https://api.example.com/', client: client);
    expect(await session.signIn('a@b.c', 'wrong'), 'Invalid login credentials.');
    expect(session.signedIn, isFalse);
    expect(await session.signIn('a@b.c', 'right'), isNull);
    expect(session.signedIn, isTrue);

    final data = ApiDataSource(session);
    expect((await data.latestRun())!.id, 7);
    expect(seen.last.url.toString(), 'https://api.example.com/api/runs/latest');

    final restored = Session('https://api.example.com', client: client);
    await restored.restore();
    expect(restored.signedIn, isTrue); // token survives a reload

    revoked = true;
    await expectLater(data.latestRun(), throwsA(isA<ApiException>()));
    expect(session.signedIn, isFalse);
  });

  test('screen and prices map the API rows', () async {
    final client = MockClient((req) async => switch (req.url.path) {
          '/api/screen/latest' => http.Response(
              jsonEncode({
                'as_of': '2026-11-15',
                'rows': [
                  {'ticker': 'AAPL', 'rank': 1, 'selected': true, 'metrics': {'sector': 'Tech'}},
                  {'ticker': 'XOM', 'rank': 300, 'selected': false, 'metrics': {}},
                ],
              }),
              200),
          '/api/prices' => http.Response(
              jsonEncode({
                'rows': [
                  {'ticker': 'AAPL', 'date': '2026-11-12', 'close': 10, 'adj_close': 9.5},
                  {'ticker': 'AAPL', 'date': '2026-11-13', 'close': null, 'adj_close': null},
                ],
              }),
              200),
          _ => http.Response(jsonEncode({'token': 'tok', 'expires_in': 60}), 200),
        });
    final session = Session('https://api.example.com', client: client);
    await session.signIn('a', 'b');
    final data = ApiDataSource(session);
    final screen = await data.latestScreen();
    expect(screen.screened, 2);
    expect(screen.picks.keys, ['AAPL']);
    expect((await data.prices('AAPL')).single.price, 9.5);
  });
}
