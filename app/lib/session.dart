import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Sign-in against the laptop's API (the same invite-only accounts as the website).
/// The signed token expires after 12 hours, and any 401 signs the user out.
class Session extends ChangeNotifier {
  Session(this.baseUrl, {http.Client? client}) : client = client ?? http.Client();

  final String baseUrl;
  final http.Client client;
  String? _token;
  DateTime? _expires;

  static const _kToken = 'ti_token';
  static const _kExpires = 'ti_token_expires';

  String? get token => _token != null && (_expires?.isAfter(DateTime.now()) ?? false) ? _token : null;
  bool get signedIn => token != null;

  Uri uri(String path, [Map<String, String>? query]) =>
      Uri.parse(baseUrl.replaceAll(RegExp(r'/+$'), '') + path).replace(queryParameters: query);

  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString(_kToken);
    _expires = DateTime.tryParse(prefs.getString(_kExpires) ?? '');
    notifyListeners();
  }

  /// Returns null on success, else a message for the login form (it never echoes the password).
  Future<String?> signIn(String username, String password) async {
    final http.Response r;
    try {
      r = await client.post(uri('/api/login'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'username': username, 'password': password}));
    } catch (_) {
      return 'Could not reach the server. It may be switched off; try again later.';
    }
    final body = _json(r.body);
    if (r.statusCode != 200 || body['token'] is! String) {
      return (body['error'] ?? 'Sign-in failed (HTTP ${r.statusCode}).').toString();
    }
    _token = body['token'] as String;
    _expires = DateTime.now().add(Duration(seconds: (body['expires_in'] as num?)?.toInt() ?? 3600));
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kToken, _token!);
    await prefs.setString(_kExpires, _expires!.toIso8601String());
    notifyListeners();
    return null;
  }

  Future<void> signOut() async {
    _token = null;
    _expires = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kToken);
    await prefs.remove(_kExpires);
    notifyListeners();
  }

  static Map<String, dynamic> _json(String s) {
    try {
      final v = jsonDecode(s);
      return v is Map<String, dynamic> ? v : <String, dynamic>{};
    } on FormatException {
      return <String, dynamic>{};
    }
  }
}
