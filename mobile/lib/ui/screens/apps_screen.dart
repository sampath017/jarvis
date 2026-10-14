import 'package:flutter/material.dart';
import '../../services/sensor_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';
import 'notes_screen.dart';
import 'reminders_screen.dart';

class AppsScreen extends StatelessWidget {
  const AppsScreen({super.key, required this.sensorService});
  final SensorService sensorService;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Apps')),
    body: WorkspaceBody(
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const PageIntro(
            title: 'Your everyday tools',
            description: 'Keep your reminders and notes together.',
          ),
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
                  builder: (_) => RemindersScreen(sensorService: sensorService),
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
