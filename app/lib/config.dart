/// Build-time configuration, passed with `--dart-define-from-file=config.json`.
class AppConfig {
  /// The laptop's API, reached through its HTTPS tunnel, e.g. https://ti-agent.example.com
  static const apiUrl = String.fromEnvironment('API_URL');
  static const benchmark = String.fromEnvironment('BENCHMARK', defaultValue: 'SPY');
  static const linkedinUrl = String.fromEnvironment('LINKEDIN_URL');
  static const githubUrl = String.fromEnvironment('GITHUB_URL', defaultValue: 'https://github.com/nsskn982');

  /// Why the app can't start, or null if the configuration is usable.
  static String? problem() => checkApiUrl(apiUrl);

  /// The sign-in token travels with every request, so anything but a local dev server must be https.
  static String? checkApiUrl(String url) {
    if (url.isEmpty) return 'Missing API_URL. Run with --dart-define-from-file=config.json.';
    final uri = Uri.tryParse(url);
    if (uri == null || uri.host.isEmpty) return 'API_URL is not a valid URL.';
    if (uri.userInfo.isNotEmpty) return 'API_URL must not contain a username or password.';
    final local = uri.host == 'localhost' || uri.host == '127.0.0.1';
    if (uri.scheme != 'https' && !(local && uri.scheme == 'http')) return 'API_URL must start with https://';
    return null;
  }
}
