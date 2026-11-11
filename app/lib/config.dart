import 'dart:convert';

/// Build-time configuration, passed with `--dart-define-from-file=config.json`.
class AppConfig {
  static const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
  static const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY');
  static const benchmark = String.fromEnvironment('BENCHMARK', defaultValue: 'SPY');
  static const linkedinUrl = String.fromEnvironment('LINKEDIN_URL');
  static const githubUrl = String.fromEnvironment('GITHUB_URL', defaultValue: 'https://github.com/nsskn982');

  /// Why the app can't start, or null if the configuration is usable.
  static String? problem() => checkKey(supabaseUrl, supabaseAnonKey);

  /// The app ships to devices, so anything in it is public. Refuse to run with a key that
  /// bypasses row-level security (service_role JWT or a new-style secret key).
  static String? checkKey(String url, String key) {
    if (url.isEmpty || key.isEmpty) {
      return 'Missing SUPABASE_URL or SUPABASE_ANON_KEY. Run with --dart-define-from-file=config.json.';
    }
    if (!url.startsWith('https://')) return 'SUPABASE_URL must start with https://';
    if (key.startsWith('sb_secret_')) return _secretKey;
    final parts = key.split('.');
    if (parts.length == 3) {
      try {
        final payload = jsonDecode(utf8.decode(base64Url.decode(base64Url.normalize(parts[1]))));
        if (payload is Map && payload['role'] == 'service_role') return _secretKey;
      } on FormatException {
        // Not a JWT we can read; let Supabase reject it if it is invalid.
      }
    }
    return null;
  }

  static const _secretKey = 'This is a service/secret key. The app must use the public anon (publishable) key; '
      'a secret key in an app bypasses all row-level security.';
}
