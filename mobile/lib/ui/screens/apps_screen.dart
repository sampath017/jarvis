import 'package:flutter/material.dart';
import '../../services/sensor_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';
import 'notes_screen.dart';
import 'reminders_screen.dart';
import 'clock_screen.dart';

class AppsScreen extends StatelessWidget {
  const AppsScreen({
    super.key,
    required this.sensorService,
    this.localOnly = false,
  });
  final SensorService sensorService;
  final bool localOnly;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Apps')),
    body: WorkspaceBody(
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          PageIntro(
            title: 'Your everyday tools',
            description: localOnly
                ? 'Clock and Notes work locally. Jarvis assistant is off.'
                : 'Your clock, reminders and notes in one place.',
          ),
          Card(
            child: ListTile(
              leading: const Icon(Icons.schedule, color: AppTheme.primary),
              title: const Text('Clock'),
              subtitle: const Text(
                'Alarms, timers, stopwatch, world clocks & bedtime',
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const ClockScreen()),
              ),
            ),
          ),
          const SizedBox(height: 16),
          if (!localOnly)
            Card(
              child: ListTile(
                leading: const Icon(
                  Icons.alarm_outlined,
                  color: AppTheme.primary,
                ),
                title: const Text('Reminders'),
                subtitle: const Text('Manage reminders and agent policies'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) =>
                        RemindersScreen(sensorService: sensorService),
                  ),
                ),
              ),
            ),
          const SizedBox(height: 16),
          Card(
            child: ListTile(
              leading: const Icon(
                Icons.note_alt_outlined,
                color: AppTheme.green,
              ),
              title: const Text('Notes'),
              subtitle: const Text('Capture and organize your thoughts'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => NotesScreen(sensorService: sensorService),
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}
