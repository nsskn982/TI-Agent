import 'package:flutter/material.dart';

import 'config.dart';
import 'data.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'theme.dart';
import 'vault.dart';

Future<void> main() async {
  // PBKDF2/AES run natively on Android and iOS (cryptography_flutter registers itself) and with
  // the browser's Web Crypto on the web.
  WidgetsFlutterBinding.ensureInitialized();
  final problem = AppConfig.problem();
  if (problem != null) {
    runApp(_ConfigError(problem));
    return;
  }
  final vault = Vault(AppConfig.resolvedDataUrl);
  await vault.restore(); // opens straight away on a device that has unlocked before
  runApp(TiApp(vault: vault));
}

class TiApp extends StatelessWidget {
  const TiApp({super.key, required this.vault});

  final Vault vault;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TI Agent',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      home: AuthGate(vault: vault),
    );
  }
}

/// Shows the unlock screen until the data file is decrypted, then the suggestions.
class AuthGate extends StatelessWidget {
  const AuthGate({super.key, required this.vault});

  final Vault vault;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: vault,
      builder: (context, _) {
        final data = vault.data;
        if (data == null) return LoginScreen(vault: vault);
        // A new key per unlock/reload so the home screen loads the new data.
        return HomeScreen(key: ObjectKey(data), data: BundleDataSource(data), onSignOut: vault.lock);
      },
    );
  }
}

class _ConfigError extends StatelessWidget {
  const _ConfigError(this.message);

  final String message;

  @override
  Widget build(BuildContext context) => MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(
          body: Center(
            child: Padding(padding: const EdgeInsets.all(24), child: Text(message, textAlign: TextAlign.center)),
          ),
        ),
      );
}
