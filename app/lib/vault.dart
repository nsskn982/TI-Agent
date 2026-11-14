import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// The app's data is one encrypted file published next to the app on GitHub Pages
/// (`orchestration/export_app.py` writes it). The password unlocks it on this device:
/// PBKDF2-SHA256 derives the key, AES-256-GCM decrypts, and a wrong password simply fails.
/// The derived key (never the password) is remembered, and stays valid until the owner
/// changes the password, which changes the file's salt.
class Vault extends ChangeNotifier {
  Vault(this.dataUrl, {http.Client? client}) : client = client ?? http.Client();

  final String dataUrl;
  final http.Client client;
  Map<String, dynamic>? data; // the decrypted bundle's "data"
  String? generatedAt;

  static const _kKey = 'ti_vault_key', _kSalt = 'ti_vault_salt';
  static final _aes = AesGcm.with256bits();

  bool get unlocked => data != null;

  Future<Map<String, dynamic>> _download() async {
    final sep = dataUrl.contains('?') ? '&' : '?';
    final r = await client.get(Uri.parse('$dataUrl${sep}t=${DateTime.now().millisecondsSinceEpoch}'));
    if (r.statusCode == 404) throw const VaultException('No data has been published yet.');
    if (r.statusCode != 200) throw VaultException('Could not download the data (HTTP ${r.statusCode}).');
    final doc = jsonDecode(r.body);
    if (doc is! Map<String, dynamic> || doc['kdf'] != 'pbkdf2-sha256' || doc['v'] != 1) {
      throw const VaultException('The data file has an unknown format. Update the app.');
    }
    return doc;
  }

  static Future<SecretKey> deriveKey(String password, Map<String, dynamic> doc) => Pbkdf2(
        macAlgorithm: Hmac.sha256(),
        iterations: (doc['iter'] as num).toInt(),
        bits: 256,
      ).deriveKeyFromPassword(password: password, nonce: base64.decode(doc['salt'] as String));

  /// Throws [SecretBoxAuthenticationError] when the key is wrong.
  static Future<Map<String, dynamic>> decrypt(Map<String, dynamic> doc, SecretKey key) async {
    final ct = base64.decode(doc['ct'] as String);
    final box = SecretBox(ct.sublist(0, ct.length - 16),
        nonce: base64.decode(doc['iv'] as String), mac: Mac(ct.sublist(ct.length - 16)));
    final clear = await _aes.decrypt(box, secretKey: key);
    return Map<String, dynamic>.from(jsonDecode(utf8.decode(clear)) as Map);
  }

  void _open(Map<String, dynamic> plain) {
    data = Map<String, dynamic>.from(plain['data'] as Map);
    generatedAt = plain['generated_at'] as String?;
    notifyListeners();
  }

  /// Opens with the remembered key, if it still fits the published file. Never throws.
  Future<bool> restore() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final k = prefs.getString(_kKey), salt = prefs.getString(_kSalt);
      if (k == null || salt == null) return false;
      final doc = await _download();
      if (doc['salt'] != salt) return false; // the password was changed
      _open(await decrypt(doc, SecretKey(base64.decode(k))));
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Returns null on success, else a message for the unlock form.
  Future<String?> unlock(String password) async {
    final Map<String, dynamic> doc;
    try {
      doc = await _download();
    } on VaultException catch (e) {
      return e.message;
    } catch (_) {
      return 'Could not reach GitHub Pages. Check your connection and try again.';
    }
    try {
      final key = await deriveKey(password, doc);
      final plain = await decrypt(doc, key);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_kKey, base64.encode(await key.extractBytes()));
      await prefs.setString(_kSalt, doc['salt'] as String);
      _open(plain);
      return null;
    } on SecretBoxAuthenticationError {
      return 'Wrong password.';
    } catch (_) {
      return 'The data file could not be read.';
    }
  }

  /// Download again (new data is published after each run).
  Future<bool> reload() async {
    if (!await restore()) {
      await lock();
      return false;
    }
    return true;
  }

  Future<void> lock() async {
    data = null;
    generatedAt = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kKey);
    await prefs.remove(_kSalt);
    notifyListeners();
  }
}

class VaultException implements Exception {
  const VaultException(this.message);

  final String message;

  @override
  String toString() => message;
}
