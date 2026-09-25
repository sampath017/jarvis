import 'package:flutter/material.dart';
import '../../services/sensor_service.dart';
import '../../services/chat_notification_service.dart';
import '../theme.dart';
import 'activity_screen.dart';
import 'chat_screen.dart';
import 'notes_screen.dart';
import 'reminders_screen.dart';
import 'settings_screen.dart';

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
      const ActivityScreen(),
      RemindersScreen(sensorService: widget.sensorService),
      NotesScreen(sensorService: widget.sensorService),
      const SettingsScreen(),
    ];
    ChatNotificationService.openThread.addListener(_openChat);
    _openChat();
    // SensorService arms context awareness after startup permissions resolve.
  }

  void _openChat() {
    if (ChatNotificationService.openThread.value == null) return;
    if (mounted) setState(() => _currentIndex = 0);
    ChatNotificationService.chatVisible.value = true;
  }

  @override
  void dispose() {
    ChatNotificationService.openThread.removeListener(_openChat);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _currentIndex, children: _screens),
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
            ChatNotificationService.chatVisible.value = index == 0;
          },
          items: const [
            BottomNavigationBarItem(
              icon: Icon(Icons.chat_bubble_outline),
              activeIcon: Icon(Icons.chat_bubble),
              label: 'Chat',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.route_outlined),
              activeIcon: Icon(Icons.route),
              label: 'Activity',
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
            BottomNavigationBarItem(
              icon: Icon(Icons.settings_outlined),
              activeIcon: Icon(Icons.settings),
              label: 'Settings',
            ),
          ],
        ),
      ),
    );
  }
}
