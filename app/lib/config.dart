/// Build-time configuration, passed with `--dart-define-from-file=config.json`.
class AppConfig {
  /// Where the encrypted data file is published. Empty = next to the app (`data/data.json`),
  /// which is right for the GitHub Pages web build; the Android build gets the full Pages URL.
  static const dataUrl = String.fromEnvironment('DATA_URL');
  static const benchmark = String.fromEnvironment('BENCHMARK', defaultValue: 'SPY');
  static const linkedinUrl = String.fromEnvironment('LINKEDIN_URL');
  static const githubUrl = String.fromEnvironment('GITHUB_URL', defaultValue: 'https://github.com/nsskn982');

  static String get resolvedDataUrl => dataUrl.isEmpty ? 'data/data.json' : dataUrl;

  /// Why the app can't start, or null if the configuration is usable.
  static String? problem() => checkDataUrl(dataUrl);

  /// A relative path (same site) or https; plain http only for a local dev server.
  static String? checkDataUrl(String url) {
    if (url.isEmpty) return null;
    final uri = Uri.tryParse(url);
    if (uri == null) return 'DATA_URL is not a valid URL.';
    if (!uri.hasScheme) return null; // relative to the app
    if (uri.userInfo.isNotEmpty) return 'DATA_URL must not contain a username or password.';
    final local = uri.host == 'localhost' || uri.host == '127.0.0.1';
    if (uri.scheme != 'https' && !(local && uri.scheme == 'http')) return 'DATA_URL must start with https://';
    return null;
  }
}
