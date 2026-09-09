import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'services/sensor_service.dart';
import 'services/sync_service.dart';
import 'ui/screens/main_navigation_screen.dart';
import 'ui/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // Set system UI to immersive dark mode matching Jarvis HUD
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
      systemNavigationBarColor: AppTheme.background,
      systemNavigationBarIconBrightness: Brightness.light,
    ),
  );

  final sensorService = SensorService();

  // Render the UI immediately so the first frame draws in milliseconds
  runApp(JarvisCollectorApp(sensorService: sensorService));

  // Initialize sensors and background sync non-blockingly in the background
  sensorService.initialize();
  SyncService().startPeriodicSync();
}

class JarvisCollectorApp extends StatelessWidget {
  final SensorService sensorService;

  const JarvisCollectorApp({super.key, required this.sensorService});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Jarvis',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      home: MainNavigationScreen(sensorService: sensorService),
    );
  }
}
