import 'package:flutter/material.dart';
import '../../services/sensor_service.dart';
import '../../services/chat_notification_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';
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
    const labels = ['Chat', 'Activity', 'Reminders', 'Notes', 'Settings'];
    const icons = [
      Icons.chat_bubble_outline,
      Icons.route_outlined,
      Icons.alarm_outlined,
      Icons.note_alt_outlined,
      Icons.settings_outlined,
    ];
    const selectedIcons = [
      Icons.chat_bubble,
      Icons.route,
      Icons.alarm,
      Icons.note_alt,
      Icons.settings,
    ];
    void select(int index) {
      setState(() => _currentIndex = index);
      ChatNotificationService.chatVisible.value = index == 0;
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 760;
        final content = IndexedStack(index: _currentIndex, children: _screens);
        return Scaffold(
          body: Row(
            children: [
              if (wide)
                SafeArea(
                  child: NavigationRail(
                    scrollable: true,
                    extended: constraints.maxWidth >= 1100,
                    labelType: constraints.maxWidth >= 1100
                        ? NavigationRailLabelType.none
                        : NavigationRailLabelType.all,
                    minWidth: 88,
                    minExtendedWidth: 220,
                    selectedIndex: _currentIndex,
                    onDestinationSelected: select,
                    leading: const Padding(
                      padding: EdgeInsets.fromLTRB(0, 20, 0, 32),
                      child: JarvisMark(size: 40),
                    ),
                    destinations: [
                      for (var i = 0; i < labels.length; i++)
                        NavigationRailDestination(
                          icon: Icon(icons[i]),
                          selectedIcon: Icon(selectedIcons[i]),
                          label: Text(labels[i]),
                        ),
                    ],
                  ),
                ),
              if (wide) const VerticalDivider(width: 1),
              Expanded(
                key: const ValueKey('workspace-content'),
                child: content,
              ),
            ],
          ),
          bottomNavigationBar: wide
              ? null
              : DecoratedBox(
                  decoration: const BoxDecoration(
                    border: Border(top: BorderSide(color: AppTheme.border)),
                  ),
                  child: NavigationBar(
                    selectedIndex: _currentIndex,
                    onDestinationSelected: select,
                    destinations: [
                      for (var i = 0; i < labels.length; i++)
                        NavigationDestination(
                          icon: Icon(icons[i]),
                          selectedIcon: Icon(selectedIcons[i]),
                          label: labels[i],
                        ),
                    ],
                  ),
                ),
        );
      },
    );
  }
}
