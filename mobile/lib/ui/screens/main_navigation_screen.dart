import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import '../../services/sensor_service.dart';
import '../theme.dart';
import 'chat_screen.dart';
import 'notes_screen.dart';
import 'reminders_screen.dart';

/// Main Navigation Root with 3 Clean Tabs:
/// 1. Chat (ChatGPT-style conversational assistant)
/// 2. Reminders (Context-aware reminders & auto-triggering)
/// 3. Notes (Context notes & trip logs)
///
/// Hardware sensors & Stage 1 Google Activity Recognition tripwire run
/// silently in the background so telemetry is logged automatically.
class MainNavigationScreen extends StatefulWidget {
  final SensorService sensorService;

  const MainNavigationScreen({super.key, required this.sensorService});

  @override
  State<MainNavigationScreen> createState() => _MainNavigationScreenState();
}

class _MainNavigationScreenState extends State<MainNavigationScreen> with WidgetsBindingObserver {
  int _currentIndex = 0;
  bool _needsBackgroundLocation = false;

  late final List<Widget> _screens;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _checkBackgroundLocation();
    _screens = [
      ChatScreen(sensorService: widget.sensorService),
      RemindersScreen(sensorService: widget.sensorService),
      NotesScreen(sensorService: widget.sensorService),
    ];
    // SensorService arms context awareness after startup permissions resolve.
  }

  Future<void> _checkBackgroundLocation() async {
    final permission = await Geolocator.checkPermission();
    if (mounted) setState(() => _needsBackgroundLocation = permission != LocationPermission.always);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _checkBackgroundLocation();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          if (_needsBackgroundLocation)
            MaterialBanner(
              content: const Text('Place history while Jarvis is closed needs Location set to “Allow all the time”. Activity changes still work without it.'),
              actions: [TextButton(
                onPressed: () => Geolocator.openAppSettings(),
                child: const Text('Open settings'),
              )],
            ),
          Expanded(child: IndexedStack(
            index: _currentIndex,
            children: _screens,
          )),
        ],
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: AppTheme.surface,
          border: Border(top: BorderSide(color: AppTheme.border)),
        ),
        child: BottomNavigationBar(
          currentIndex: _currentIndex,
          backgroundColor: AppTheme.surface,
          selectedItemColor: AppTheme.primary,
          unselectedItemColor: AppTheme.textSecondary,
          selectedFontSize: 12,
          unselectedFontSize: 12,
          selectedLabelStyle: const TextStyle(fontWeight: FontWeight.w600),
          unselectedLabelStyle: const TextStyle(fontWeight: FontWeight.w500),
          type: BottomNavigationBarType.fixed,
          elevation: 0,
          onTap: (index) {
            setState(() => _currentIndex = index);
          },
          items: const [
            BottomNavigationBarItem(
              icon: Icon(Icons.chat_bubble_outline),
              activeIcon: Icon(Icons.chat_bubble),
              label: 'Chat',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.alarm),
              activeIcon: Icon(Icons.alarm_on),
              label: 'Reminders',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.note_alt_outlined),
              activeIcon: Icon(Icons.note_alt),
              label: 'Notes',
            ),
          ],
        ),
      ),
    );
  }
}
