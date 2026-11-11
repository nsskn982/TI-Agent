import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config.dart';
import 'data.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final problem = AppConfig.problem();
  if (problem != null) {
    runApp(_ConfigError(problem));
    return;
  }
  await Supabase.initialize(url: AppConfig.supabaseUrl, anonKey: AppConfig.supabaseAnonKey);
  runApp(const TiApp());
}

class TiApp extends StatelessWidget {
  const TiApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TI Agent',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      home: const AuthGate(),
    );
  }
}

/// Shows the login screen until there is a Supabase session, then the suggestions.
class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    final client = Supabase.instance.client;
    return StreamBuilder<AuthState>(
      stream: client.auth.onAuthStateChange,
      builder: (context, _) {
        if (client.auth.currentSession == null) return const LoginScreen();
        return HomeScreen(data: SupabaseDataSource(client), onSignOut: () => client.auth.signOut());
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
