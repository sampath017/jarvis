import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class DatabaseBackupSettings extends StatefulWidget {
  const DatabaseBackupSettings({super.key});
  @override
  State<DatabaseBackupSettings> createState() => _DatabaseBackupSettingsState();
}

class _DatabaseBackupSettingsState extends State<DatabaseBackupSettings> {
  static const channel = MethodChannel('com.jarvis/database_backup');
  Map<String, dynamic> status = {};
  bool busy = false;
  String? error;

  @override
  void initState() {
    super.initState();
    load('status');
  }

  Future<void> load(String method, [dynamic value]) async {
    setState(() => busy = true);
    try {
      final next = await channel.invokeMapMethod<String, dynamic>(
        method,
        value,
      );
      if (mounted)
        setState(() {
          status = next ?? {};
          error = null;
        });
    } on PlatformException catch (failure) {
      if (mounted) setState(() => error = failure.message);
    } on MissingPluginException {
      if (mounted)
        setState(
          () => error = 'Install the updated Android app to use backups.',
        );
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final success = (status['lastSuccess'] as num?)?.toInt() ?? 0;
    final last = success == 0
        ? 'No completed backup yet.'
        : 'Last backup: ${DateTime.fromMillisecondsSinceEpoch(success).toLocal().toString().substring(0, 16)}';
    return Card(
      child: Column(
        children: [
          SwitchListTile(
            title: const Text('Weekly Drive backup'),
            subtitle: const Text(
              'Sunday, 3:00 AM • Jarvis/jarvis_db_backup.db\nKeeps the latest database backup only.',
            ),
            isThreeLine: true,
            value: status['enabled'] != false,
            onChanged: busy ? null : (value) => load('configure', value),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Text(
              error ??
                  status['error']?.toString() ??
                  (status['connected'] == false
                      ? 'Connect Google Drive to start backing up.'
                      : '$last ${status['state'] == 'queued'
                            ? 'Waiting for network and battery.'
                            : status['state'] == 'running'
                            ? 'Backup in progress.'
                            : ''}'),
            ),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                onPressed: busy ? null : () => load('status'),
                child: const Text('Refresh'),
              ),
              TextButton(
                onPressed:
                    busy ||
                        status['enabled'] == false ||
                        status['connected'] != true
                    ? null
                    : () => load('backupNow'),
                child: const Text('Back up now'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
