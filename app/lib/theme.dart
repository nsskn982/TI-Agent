import 'package:flutter/material.dart';

import 'models.dart';

/// Same palette as the website (validated for light and dark, colour-blind safe pair).
class TiColors {
  static bool _dark(BuildContext c) => Theme.of(c).brightness == Brightness.dark;

  static Color series1(BuildContext c) => _dark(c) ? const Color(0xFF3987E5) : const Color(0xFF2A78D6);
  static Color series2(BuildContext c) => _dark(c) ? const Color(0xFFD95926) : const Color(0xFFEB6834);
  static Color muted(BuildContext c) => const Color(0xFF898781);
  static Color ink2(BuildContext c) => _dark(c) ? const Color(0xFFC3C2B7) : const Color(0xFF52514E);
  static Color border(BuildContext c) => _dark(c) ? const Color(0x1AFFFFFF) : const Color(0x1A0B0B0B);
  static Color grid(BuildContext c) => _dark(c) ? const Color(0xFF2C2C2A) : const Color(0xFFE1E0D9);

  static Color stance(BuildContext c, Stance s) => switch (s) {
        Stance.bullish => series1(c),
        Stance.bearish => _dark(c) ? const Color(0xFFE66767) : const Color(0xFFE34948),
        Stance.neutral => muted(c),
      };
}

/// Colour with an opacity, without the deprecated withOpacity.
Color fade(Color c, double opacity) => c.withAlpha((opacity.clamp(0.0, 1.0) * 255).round());

ThemeData buildTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(seedColor: const Color(0xFF2A78D6), brightness: brightness).copyWith(
    surface: dark ? const Color(0xFF1A1A19) : const Color(0xFFFCFCFB),
    onSurface: dark ? const Color(0xFFF0EFEC) : const Color(0xFF0B0B0B),
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: dark ? const Color(0xFF0D0D0D) : const Color(0xFFF9F9F7),
    appBarTheme: AppBarTheme(
      backgroundColor: dark ? const Color(0xFF0D0D0D) : const Color(0xFFF9F9F7),
      surfaceTintColor: Colors.transparent,
      scrolledUnderElevation: 0,
    ),
  );
}
