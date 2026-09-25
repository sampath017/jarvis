import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_service.dart';
import '../../services/local_db_service.dart';
import '../../services/sync_service.dart';
import '../theme.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen>
    with WidgetsBindingObserver {
  static const _channel = MethodChannel('com.jarvis/foreground_service');
  final ApiService _api = ApiService();
  final LocalDbService _db = LocalDbService();
  bool _checking = true;
  bool _syncing = false;
  bool _connected = false;
  bool? _notificationsEnabled;
  int _cachedDays = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<void> _refresh() async {
    if (mounted) setState(() => _checking = true);
    final connected = await _api.checkHealth();
    bool? notifications;
    try {
      notifications = await _channel.invokeMethod<bool>('notificationsEnabled');
    } catch (_) {}
    final days = await _db.activityCacheDayCount();
    if (!mounted) return;
    setState(() {
      _connected = connected;
      _notificationsEnabled = notifications;
      _cachedDays = days;
      _checking = false;
    });
  }

  Future<void> _syncNow() async {
    setState(() => _syncing = true);
    final online = await _api.checkHealth();
    if (online) await SyncService().syncNow();
    if (!mounted) return;
    setState(() {
      _connected = online;
      _syncing = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          online
              ? 'Sync checked. Pull down in Activity for the latest day.'
              : 'Jarvis is offline. Your changes will sync when it reconnects.',
        ),
      ),
    );
  }

  Future<void> _openNotificationSettings() async {
    try {
      await _channel.invokeMethod('openNotificationSettings');
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Could not open notification settings.'),
          ),
        );
      }
    }
  }

  Future<void> _clearActivityCache() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear offline activity?'),
        content: const Text(
          'This removes saved Activity days from this phone. Your Firebase history stays available and can be loaded again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Clear cache'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _db.clearActivityCache();
    if (mounted) {
      setState(() => _cachedDays = 0);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Offline activity cache cleared.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 20, 16, 96),
        children: [
          _sectionLabel('Sync & backup'),
          _card(
            children: [
              ListTile(
                leading: Icon(
                  _connected
                      ? Icons.cloud_done_outlined
                      : Icons.cloud_off_outlined,
                  color: _connected ? AppTheme.green : AppTheme.amber,
                ),
                title: const Text('Cloud connection'),
                subtitle: Text(
                  _checking
                      ? 'Checking…'
                      : _connected
                      ? 'Connected to Jarvis'
                      : 'Offline — saved changes will retry',
                ),
              ),
              const Divider(height: 1, color: AppTheme.border),
              ListTile(
                leading: const Icon(Icons.sync, color: AppTheme.primary),
                title: const Text('Sync now'),
                subtitle: const Text('Update reminders, notes and chats'),
                trailing: _syncing
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.chevron_right),
                onTap: _syncing ? null : _syncNow,
              ),
            ],
          ),
          const SizedBox(height: 28),
          _sectionLabel('Alerts'),
          _card(
            children: [
              ListTile(
                leading: const Icon(
                  Icons.notifications_outlined,
                  color: AppTheme.primary,
                ),
                title: const Text('Reminder notifications'),
                subtitle: Text(
                  _notificationsEnabled == null
                      ? 'Manage phone alert settings'
                      : _notificationsEnabled!
                      ? 'On · manage sounds and delivery'
                      : 'Off · reminders may be missed',
                ),
                trailing: const Icon(Icons.open_in_new, size: 18),
                onTap: _openNotificationSettings,
              ),
            ],
          ),
          const SizedBox(height: 28),
          _sectionLabel('On this phone'),
          _card(
            children: [
              ListTile(
                leading: const Icon(
                  Icons.offline_pin_outlined,
                  color: AppTheme.primary,
                ),
                title: const Text('Saved Activity days'),
                subtitle: Text(
                  '$_cachedDays ${_cachedDays == 1 ? 'day' : 'days'} available offline',
                ),
                trailing: TextButton(
                  onPressed: _cachedDays == 0 ? null : _clearActivityCache,
                  child: const Text('Clear'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              'Activity history contains sampled observations. Missing periods cannot be reconstructed.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }

  Widget _sectionLabel(String text) => Padding(
    padding: const EdgeInsets.fromLTRB(8, 0, 8, 10),
    child: Text(
      text,
      style: const TextStyle(
        color: AppTheme.textSecondary,
        fontSize: 13,
        fontWeight: FontWeight.w600,
      ),
    ),
  );

  Widget _card({required List<Widget> children}) => Container(
    decoration: BoxDecoration(
      color: AppTheme.surface,
      borderRadius: BorderRadius.circular(18),
      border: Border.all(color: AppTheme.border),
    ),
    clipBehavior: Clip.antiAlias,
    child: Column(children: children),
  );
}
