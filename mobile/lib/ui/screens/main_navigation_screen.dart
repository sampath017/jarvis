import 'package:flutter/material.dart';
import '../../services/sensor_service.dart';
import '../../services/chat_notification_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';
import 'personal_dashboard_screen.dart';
import 'chat_screen.dart';
import 'apps_screen.dart';
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
      const SizedBox.shrink(),
      const SizedBox.shrink(),
      const SizedBox.shrink(),
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
    const labels = ['Chat', 'Overview', 'Apps', 'Settings'];
    const icons = [
      Icons.chat_bubble_outline,
      Icons.dashboard_outlined,
      Icons.apps_outlined,
      Icons.settings_outlined,
    ];
    const selectedIcons = [
      Icons.chat_bubble,
      Icons.dashboard,
      Icons.apps,
      Icons.settings,
    ];
    void select(int index) {
      setState(() {
        if (index == 1 && _screens[1] is! PersonalDashboardScreen) {
          _screens[1] = const PersonalDashboardScreen();
        }
        if (index == 2 && _screens[2] is! AppsScreen) {
          _screens[2] = AppsScreen(sensorService: widget.sensorService);
        }
        if (index == 3 && _screens[3] is! SettingsScreen) {
          _screens[3] = const SettingsScreen();
        }
        _currentIndex = index;
      });
      ChatNotificationService.chatVisible.value = index == 0;
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 760;
        final content = IndexedStack(
          index: _currentIndex,
          children: [
            for (var i = 0; i < _screens.length; i++)
              TickerMode(enabled: i == _currentIndex, child: _screens[i]),
          ],
        );
        return Scaffold(
          body: Row(
            children: [
              if (wide)
                ColoredBox(
                  color: AppTheme.sidebar,
                  child: SafeArea(
                    child: NavigationRail(
                      scrollable: true,
                      extended: constraints.maxWidth >= 1100,
                      labelType: constraints.maxWidth >= 1100
                          ? NavigationRailLabelType.none
                          : NavigationRailLabelType.all,
                      minWidth: 88,
                      minExtendedWidth: 196,
                      selectedIndex: _currentIndex,
                      onDestinationSelected: select,
                      leading: Padding(
                        padding: const EdgeInsets.fromLTRB(16, 20, 16, 36),
                        child: constraints.maxWidth >= 1100
                            ? const Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  JarvisMark(size: 34),
                                  SizedBox(width: 12),
                                  Text(
                                    'Jarvis',
                                    style: TextStyle(
                                      fontSize: 22,
                                      fontWeight: FontWeight.w600,
                                      letterSpacing: -0.7,
                                    ),
                                  ),
                                ],
                              )
                            : const JarvisMark(size: 36),
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
                    labelBehavior:
                        MediaQuery.textScalerOf(context).scale(14) > 18
                        ? NavigationDestinationLabelBehavior.onlyShowSelected
                        : NavigationDestinationLabelBehavior.alwaysShow,
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
