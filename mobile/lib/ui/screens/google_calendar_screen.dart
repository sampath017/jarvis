import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../services/calendar_executor.dart';
import '../../services/google_calendar_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';

class GoogleCalendarScreen extends StatefulWidget {
  const GoogleCalendarScreen({super.key});
  @override
  State<GoogleCalendarScreen> createState() => _GoogleCalendarScreenState();
}

class _GoogleCalendarScreenState extends State<GoogleCalendarScreen> {
  final _service = GoogleCalendarService.instance;
  bool _busy = false;
  String? _error;
  List<Map<String, dynamic>> _calendars = [];
  @override
  void initState() {
    super.initState();
    _service.addListener(_changed);
    _load();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _service.removeListener(_changed);
    super.dispose();
  }

  Future<void> _load() async {
    await _service.restoreConnection();
    await _service.refresh();
    if (_service.connected) {
      await _run(() async {
        _calendars = await _service.calendars();
      });
    }
    if (mounted) setState(() {});
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) {
        setState(
          () => _error = e is PlatformException
              ? e.message
              : e is CalendarFailure
              ? e.message
              : 'Could not connect to Google Calendar. Try again.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Google Calendar')),
    body: WorkspaceBody(
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const PageIntro(
            title: 'Your schedule, with your approval',
            description:
                'Read your schedule and manage events through Jarvis chat.',
          ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(
                        Icons.calendar_month_outlined,
                        color: AppTheme.primaryLight,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          _service.connected
                              ? _service.email
                              : 'Connect Google Calendar',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  if (_service.connected)
                    const Text(
                      'Connected',
                      style: TextStyle(color: AppTheme.green),
                    ),
                  const Text(
                    'Jarvis can read your calendars and events. Creating, editing, deleting events, and sending invitations always require a preview and your approval.',
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Keep Jarvis open while using calendar commands. Your Google access token stays on this phone. Relevant event details are sent to Jarvis to answer your request.',
                    style: TextStyle(color: AppTheme.textSecondary),
                  ),
                  const SizedBox(height: 20),
                  if (_busy || _service.restoring)
                    const LinearProgressIndicator()
                  else
                    Wrap(
                      spacing: 12,
                      runSpacing: 12,
                      children: [
                        if (!_service.connected)
                          FilledButton.icon(
                            onPressed: () => _run(() async {
                              _calendars = await _service.connect();
                            }),
                            icon: const Icon(Icons.link),
                            label: Text(
                              _service.needsReconnect
                                  ? 'Reconnect Google account'
                                  : 'Connect Google account',
                            ),
                          ),
                        if (_service.connected)
                          OutlinedButton(
                            onPressed: () async {
                              final confirmed = await showDialog<bool>(
                                context: context,
                                builder: (ctx) => AlertDialog(
                                  title: const Text(
                                    'Disconnect Google Calendar?',
                                  ),
                                  content: const Text(
                                    'Jarvis will lose calendar access on this phone. You can also remove Jarvis’s permission in your Google account settings.',
                                  ),
                                  actions: [
                                    TextButton(
                                      onPressed: () =>
                                          Navigator.pop(ctx, false),
                                      child: const Text('Cancel'),
                                    ),
                                    FilledButton(
                                      onPressed: () => Navigator.pop(ctx, true),
                                      child: const Text('Disconnect'),
                                    ),
                                  ],
                                ),
                              );
                              if (confirmed == true) {
                                await _run(() async {
                                  await _service.disconnect();
                                  _calendars = [];
                                });
                              }
                            },
                            child: const Text('Disconnect'),
                          ),
                      ],
                    ),
                ],
              ),
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Text(
                _error!,
                style: const TextStyle(color: AppTheme.amber),
              ),
            ),
          if (_service.connected && _calendars.isNotEmpty) ...[
            const SizedBox(height: 24),
            Text(
              'Default calendar',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            const Text(
              'New events use this calendar unless you choose another in chat.',
            ),
            const SizedBox(height: 12),
            Card(
              child: Column(
                children: [
                  for (final calendar in _calendars)
                    ListTile(
                      leading: Icon(
                        calendar['id'] == _service.calendarId
                            ? Icons.radio_button_checked
                            : Icons.radio_button_unchecked,
                        color: AppTheme.primaryLight,
                      ),
                      title: Text(
                        calendar['summary']?.toString() ??
                            calendar['id'].toString(),
                      ),
                      subtitle: Text(
                        '${calendar['timeZone'] ?? ''} · ${['owner', 'writer'].contains(calendar['accessRole']) ? 'Can edit' : 'Read only'}',
                      ),
                      onTap: _busy
                          ? null
                          : () => _run(
                              () => _service.selectCalendar(
                                calendar['id'].toString(),
                              ),
                            ),
                    ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 24),
          const Text(
            'Try in chat: “What’s on my calendar tomorrow?” or “Schedule a meeting on Friday at 3 PM.”',
          ),
        ],
      ),
    ),
  );
}
