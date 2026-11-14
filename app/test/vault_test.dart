import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ti_agent/data.dart';
import 'package:ti_agent/vault.dart';

/// test/fixtures/sample_data.json was written by the real Python exporter
/// (orchestration/export_app.py, password "test-password-123", 1000 iterations), so this also
/// checks that the two sides agree on PBKDF2 + AES-GCM.
void main() {
  late String fixture;
  setUpAll(() => fixture = File('test/fixtures/sample_data.json').readAsStringSync());
  setUp(() => SharedPreferences.setMockInitialValues({}));

  MockClient serve(String Function() body, {int status = 200}) => MockClient((req) async {
        expect(req.url.path, endsWith('data/data.json'));
        return http.Response(body(), status);
      });

  test('wrong password fails, right one decrypts what Python encrypted', () async {
    final v = Vault('https://x.github.io/TI-Agent/data/data.json', client: serve(() => fixture));
    expect(await v.unlock('not the password'), 'Wrong password.');
    expect(v.unlocked, isFalse);
    expect(await v.unlock('test-password-123'), isNull);
    expect(v.unlocked, isTrue);
    expect(v.generatedAt, '2026-11-14T18:00:00+00:00');
  });

  test('the data source maps the bundle', () async {
    final v = Vault('data/data.json', client: serve(() => fixture));
    await v.unlock('test-password-123');
    final ds = BundleDataSource(v.data!);
    final run = await ds.latestRun();
    expect(run!.id, 2);
    expect((await ds.previousRun(2))!.id, 1);
    expect((await ds.suggestionsForRun(2)).single.ticker, 'ANF');
    expect((await ds.tickerHistory('ANF')).length, 2);
    final screen = await ds.latestScreen();
    expect(screen.screened, 2);
    expect(screen.picks.keys, ['ANF']);
    expect((await ds.citations([7, 99])).keys, [7]);
  });

  test('a device remembers the key until the password changes', () async {
    var body = fixture;
    final client = serve(() => body);
    await Vault('data/data.json', client: client).unlock('test-password-123');

    final again = Vault('data/data.json', client: client);
    expect(await again.restore(), isTrue); // no password needed on reload
    expect(again.unlocked, isTrue);

    final doc = Map<String, dynamic>.from(jsonDecode(fixture) as Map)..['salt'] = base64.encode(List.filled(16, 7));
    body = jsonEncode(doc); // owner re-encrypted with a new password
    expect(await Vault('data/data.json', client: client).restore(), isFalse);
  });

  test('nothing published yet', () async {
    final v = Vault('data/data.json', client: serve(() => 'not found', status: 404));
    expect(await v.unlock('test-password-123'), 'No data has been published yet.');
  });
}
