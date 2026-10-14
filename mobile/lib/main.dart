import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'services/sensor_service.dart';
import 'services/sync_service.dart';
import 'services/chat_notification_service.dart';
import 'services/usage_service.dart';
import 'services/google_calendar_service.dart';
import 'services/google_drive_service.dart';
import 'services/api_service.dart';
import 'services/mobile_store.dart';
import 'services/power_http.dart' as http;
import 'services/runtime_power_service.dart';
import 'services/power_state.dart';
import 'ui/screens/settings_screen.dart';
import 'ui/screens/main_navigation_screen.dart';
import 'ui/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  http.mobileChangesWriter = MobileStore.instance.apply;

  // Match the dark, edge-to-edge application surface.
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
      systemNavigationBarColor: AppTheme.background,
      systemNavigationBarIconBrightness: Brightness.light,
    ),
  );

  final sensorService = SensorService();
  PowerState.setEnabled(false); // Wait for the durable phone/cloud state.
  ApiService().locationReader = () => sensorService.getCurrentLocation(
    requestIfNeeded: true,
    reportFailure: true,
  );

  // Render the UI immediately so the first frame draws in milliseconds
  runApp(JarvisCollectorApp(sensorService: sensorService));

  final power = RuntimePowerService.instance;
  power.startServices = () async {
    if (!power.enabled) return;
    ChatNotificationService.initialize();
    UsageService.initialize();
    ApiService().resumeAfterPowerOn();
    GoogleCalendarService.instance.restoreConnection();
    GoogleDriveService.instance.restoreConnection().then((_) {
      if (power.enabled) GoogleDriveService.instance.loadCloudMemories();
    });
    final native =
        await RuntimePowerService.channel.invokeMapMethod<String, dynamic>(
          'status',
        ) ??
        {};
    if (!power.enabled) return;
    await sensorService.initialize(
      startMonitoring: native['resumeMonitoring'] != false,
    );
    if (power.enabled) SyncService().startPeriodicSync();
  };
  power.stopServices = () async {
    ApiService().pauseForPowerOff();
    SyncService().stopPeriodicSync();
    await sensorService.suspendForPowerOff();
  };
  // Local reads open SQLite on demand. Let Flutter paint before restoring
  // sensors, accounts and scheduled work.
  WidgetsBinding.instance.addPostFrameCallback((_) {
    power.initialize();
  });
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
      home: ListenableBuilder(
        listenable: RuntimePowerService.instance,
        builder: (_, _) {
          final power = RuntimePowerService.instance;
          if (power.initialized && !power.enabled) {
            return const SettingsScreen();
          }
          return Stack(
            children: [
              MainNavigationScreen(sensorService: sensorService),
              if (!power.initialized)
                const Positioned(
                  top: 0,
                  left: 0,
                  right: 0,
                  child: SafeArea(child: LinearProgressIndicator()),
                ),
            ],
          );
        },
      ),
    );
  }
}
