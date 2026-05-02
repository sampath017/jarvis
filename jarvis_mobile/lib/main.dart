import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'ui/screens/home_screen.dart';
import 'ui/screens/login_screen.dart';
import 'providers/auth_provider.dart';

import 'package:firebase_core/firebase_core.dart';
import 'firebase_options.dart';

// SET THIS TO TRUE TO SKIP LOGIN SCREEN
const bool DEBUG_BYPASS = false;

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );

  if (DEBUG_BYPASS) {
    // Attempt to sign in anonymously automatically
    try {
      await FirebaseAuth.instance.signInAnonymously();
    } catch (e) {
      debugPrint('Auto-login failed: $e');
    }
  }

  runApp(
    const ProviderScope(
      child: JarvisTasksApp(),
    ),
  );
}

class JarvisTasksApp extends ConsumerWidget {
  const JarvisTasksApp({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authStateProvider);

    return MaterialApp(
      title: 'Javris',
      debugShowCheckedModeBanner: false,
      themeMode: ThemeMode.dark,
      darkTheme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF111114),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF2563EB),
          surface: Color(0xFF111114),
          surfaceContainerLow: Color(0xFF1E1E24), // Used for tabs and cards
          onSurface: Color(0xFFF0F0F2),
          onSurfaceVariant: Color(0xFFA0A0C0),
        ),
      ),
      home: authState.when(
        data: (user) => user == null ? const LoginScreen() : const HomeScreen(),
        loading: () => const Scaffold(body: Center(child: CircularProgressIndicator(color: Color(0xFF2563EB)))),
        error: (err, stack) => Scaffold(body: Center(child: Text('Error: $err'))),
      ),
    );
  }
}
