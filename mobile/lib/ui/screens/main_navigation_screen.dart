import 'package:flutter/material.dart';
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

class _MainNavigationScreenState extends State<MainNavigationScreen> {
  int _currentIndex = 0;

  late final List<Widget> _screens;

  @override
  void initState() {
    super.initState();
    _screens = [
      ChatScreen(sensorService: widget.sensorService),
      RemindersScreen(sensorService: widget.sensorService),
      NotesScreen(sensorService: widget.sensorService),
    ];
    // Automatically arm the low-power Stage 1 GAR tripwire in the background
    widget.sensorService.startTripwire();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: _screens,
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: AppTheme.surface,
          border: Border(top: BorderSide(color: AppTheme.border, width: 0.8)),
        ),
        child: BottomNavigationBar(
          currentIndex: _currentIndex,
          backgroundColor: AppTheme.surface,
          selectedItemColor: AppTheme.primary,
          unselectedItemColor: AppTheme.textSecondary,
          selectedFontSize: 12,
          unselectedFontSize: 11,
          type: BottomNavigationBarType.fixed,
          elevation: 8,
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
