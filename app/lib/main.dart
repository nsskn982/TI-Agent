import 'package:flutter/material.dart';

import 'config.dart';
import 'data.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'session.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final problem = AppConfig.problem();
  if (problem != null) {
    runApp(_ConfigError(problem));
    return;
  }
  final session = Session(AppConfig.apiUrl);
  await session.restore();
  runApp(TiApp(session: session));
}

class TiApp extends StatelessWidget {
  const TiApp({super.key, required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TI Agent',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      home: AuthGate(session: session),
    );
  }
}

/// Shows the login screen until there is a valid token, then the suggestions.
class AuthGate extends StatelessWidget {
  const AuthGate({super.key, required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: session,
      builder: (context, _) {
        if (!session.signedIn) return LoginScreen(session: session);
        return HomeScreen(data: ApiDataSource(session), onSignOut: session.signOut);
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
