import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_service.dart';
import '../../services/local_db_service.dart';
import '../../services/sync_service.dart';
import '../../services/usage_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';
import 'google_calendar_screen.dart';
import '../../services/google_calendar_service.dart';
import '../../services/google_drive_service.dart';
import 'google_drive_screen.dart';

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
  bool _usageAllowed = false;
  bool _usageDaily = true;
  bool _exactAlarms = false;
  bool? _backgroundLocation;
  bool? _locationEnabled;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
    GoogleCalendarService.instance.addListener(_calendarChanged);
    GoogleCalendarService.instance.refresh();
    GoogleDriveService.instance.addListener(_calendarChanged);
    GoogleDriveService.instance.refresh();
  }

  void _calendarChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    GoogleCalendarService.instance.removeListener(_calendarChanged);
    GoogleDriveService.instance.removeListener(_calendarChanged);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<void> _refresh() async {
    if (mounted) setState(() => _checking = true);
    await Future.wait([
      GoogleCalendarService.instance.refresh(),
      GoogleDriveService.instance.refresh(),
    ]);
    final connected = await _api.checkHealth();
    bool? notifications;
    try {
      notifications = await _channel.invokeMethod<bool>('notificationsEnabled');
    } catch (_) {}
    Map<dynamic, dynamic> usage = {};
    try {
      usage = await UsageService.channel.invokeMapMethod('status') ?? {};
    } catch (_) {}
    final days = await _db.activityCacheDayCount();
    Map<dynamic, dynamic> location = {};
    try {
      location = await _channel.invokeMapMethod('contextLocationStatus') ?? {};
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      _connected = connected;
      _notificationsEnabled = notifications;
      _cachedDays = days;
      _usageAllowed = usage['allowed'] == true;
      _usageDaily = usage['enabled'] != false;
      _exactAlarms = usage['exact'] == true;
      _backgroundLocation = location['background'] as bool?;
      _locationEnabled = location['enabled'] as bool?;
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
      body: WorkspaceBody(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 96),
          children: [
            const PageIntro(
              title: 'Make Jarvis work for you',
              description:
                  'Manage your connections, preferences, and notifications.',
            ),
            _sectionLabel('Account'),
            _card(
              children: [
                ExpansionTile(
                  leading: const Icon(
                    Icons.account_circle_outlined,
                    color: AppTheme.primaryLight,
                  ),
                  title: const Text('Connected accounts'),
                  subtitle: Text(_accountSummary),
                  children: [
                    ListTile(
                      leading: Icon(
                        GoogleCalendarService.instance.connected
                            ? Icons.check_circle_outline
                            : Icons.calendar_month_outlined,
                        color: GoogleCalendarService.instance.connected
                            ? AppTheme.green
                            : AppTheme.primaryLight,
                      ),
                      title: const Text('Google Calendar'),
                      subtitle: Text(
                        _connectionStatus(
                          GoogleCalendarService.instance.connected,
                          GoogleCalendarService.instance.needsReconnect,
                          GoogleCalendarService.instance.restoring,
                          GoogleCalendarService.instance.email,
                        ),
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => const GoogleCalendarScreen(),
                        ),
                      ),
                    ),
                    ListTile(
                      leading: Icon(
                        GoogleDriveService.instance.connected
                            ? Icons.check_circle_outline
                            : Icons.add_to_drive_outlined,
                        color: GoogleDriveService.instance.connected
                            ? AppTheme.green
                            : AppTheme.primaryLight,
                      ),
                      title: const Text('Google Drive'),
                      subtitle: Text(
                        _connectionStatus(
                          GoogleDriveService.instance.connected,
                          GoogleDriveService.instance.needsReconnect,
                          GoogleDriveService.instance.restoring,
                          GoogleDriveService.instance.email,
                        ),
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => const GoogleDriveScreen(),
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 24),
            _sectionLabel('Activity & location'),
            _card(
              children: [
                ListTile(
                  leading: Icon(
                    Icons.location_on_outlined,
                    color:
                        _backgroundLocation == true && _locationEnabled == true
                        ? AppTheme.green
                        : AppTheme.amber,
                  ),
                  title: const Text('Background location'),
                  subtitle: Text(
                    _locationEnabled == false
                        ? 'Phone location is off. Turn it on to record places during trips.'
                        : _backgroundLocation == true
                        ? 'Allowed · places are sampled during activity changes'
                        : _backgroundLocation == false
                        ? 'Missing · choose Permissions → Location → Allow all the time. Rides may have no places until enabled.'
                        : 'Check Permissions → Location → Allow all the time',
                  ),
                  trailing: const Icon(Icons.open_in_new, size: 18),
                  onTap: () async {
                    try {
                      await _channel.invokeMethod('openLocationSettings');
                    } catch (_) {
                      if (!context.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text(
                            'Open Android Settings → Apps → Jarvis → Permissions → Location.',
                          ),
                        ),
                      );
                    }
                  },
                ),
              ],
            ),
            const SizedBox(height: 24),
            _sectionLabel('Screen time'),
            _card(
              children: [
                ListTile(
                  leading: const Icon(
                    Icons.query_stats,
                    color: AppTheme.primary,
                  ),
                  title: const Text('Usage Access'),
                  subtitle: Text(
                    _usageAllowed
                        ? 'Connected · foreground time for your apps'
                        : 'Allow Jarvis to read time spent in your apps',
                  ),
                  trailing: Icon(
                    _usageAllowed
                        ? Icons.check_circle_outline
                        : Icons.chevron_right,
                  ),
                  onTap: () => UsageService.channel.invokeMethod('openAccess'),
                ),
                const Divider(height: 1, color: AppTheme.border),
                SwitchListTile(
                  title: const Text('Daily report at 11 PM'),
                  subtitle: const Text(
                    'Midnight–11 PM IST · notification with an app breakdown',
                  ),
                  value: _usageDaily,
                  onChanged: (enabled) async {
                    await UsageService.channel.invokeMethod(
                      'setEnabled',
                      enabled,
                    );
                    if (mounted) setState(() => _usageDaily = enabled);
                  },
                ),
                ListTile(
                  leading: const Icon(Icons.schedule, color: AppTheme.primary),
                  title: const Text('Alarms & reminders'),
                  subtitle: Text(
                    _exactAlarms
                        ? 'Precise scheduling allowed · no Clock alarm'
                        : 'Allow precise timing; otherwise Android may deliver late',
                  ),
                  trailing: Icon(
                    _exactAlarms
                        ? Icons.check_circle_outline
                        : Icons.chevron_right,
                  ),
                  onTap: () =>
                      UsageService.channel.invokeMethod('openExactAlarm'),
                ),
                ListTile(
                  title: const Text('View today’s screen time'),
                  subtitle: const Text(
                    'You can also ask “Instagram usage today” in chat',
                  ),
                  onTap: () async {
                    final text = await UsageService.answer('screen time today');
                    if (!context.mounted) return;
                    showDialog(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        title: const Text('Today’s app usage'),
                        content: SingleChildScrollView(
                          child: SelectableText(text),
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(ctx),
                            child: const Text('Close'),
                          ),
                        ],
                      ),
                    );
                  },
                ),
              ],
            ),
            const SizedBox(height: 24),
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
      ),
    );
  }

  String get _accountSummary {
    final drive = GoogleDriveService.instance;
    final calendar = GoogleCalendarService.instance;
    if (drive.restoring || calendar.restoring) {
      return 'Checking saved Google access…';
    }
    if (drive.needsReconnect || calendar.needsReconnect) {
      return 'Google access needs attention';
    }
    if (drive.connected && calendar.connected) {
      return drive.email == calendar.email
          ? '${drive.email}\nDrive and Calendar connected'
          : 'Drive and Calendar connected · 2 accounts';
    }
    if (drive.connected) return '${drive.email}\nDrive connected';
    if (calendar.connected) return '${calendar.email}\nCalendar connected';
    return 'Manage Google Drive and Calendar';
  }

  String _connectionStatus(
    bool connected,
    bool needsReconnect,
    bool restoring,
    String email,
  ) {
    if (restoring) return 'Checking saved access…';
    if (connected) return 'Connected · $email';
    return needsReconnect ? 'Reconnect to renew access' : 'Not connected';
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

  Widget _card({required List<Widget> children}) => Material(
    color: AppTheme.surface,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(AppTheme.radius),
      side: const BorderSide(color: AppTheme.border),
    ),
    clipBehavior: Clip.antiAlias,
    child: Column(children: children),
  );
}
