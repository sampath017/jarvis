import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:wakelock_plus/wakelock_plus.dart';
import '../../services/clock_service.dart';
import '../theme.dart';

class ClockScreen extends StatefulWidget {
  const ClockScreen({super.key, this.service});
  final ClockService? service;
  @override
  State<ClockScreen> createState() => _ClockScreenState();
}

class _ClockScreenState extends State<ClockScreen> with WidgetsBindingObserver {
  late final ClockService service = widget.service ?? ClockService();
  Map<String, dynamic> state = {};
  int tab = 0;
  Timer? ticker;
  bool loading = true, busy = false, reading = false;
  String? error;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    refresh();
    startTicker();
  }

  void startTicker() {
    ticker?.cancel();
    ticker = Timer.periodic(
      const Duration(milliseconds: 250),
      (_) => refresh(silent: true),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState value) {
    if (value == AppLifecycleState.resumed) {
      refresh();
      startTicker();
    } else {
      ticker?.cancel();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    ticker?.cancel();
    super.dispose();
  }

  Future<void> refresh({bool silent = false}) async {
    if (reading || busy) return;
    reading = true;
    try {
      final next = await service.execute('snapshot');
      if (mounted) {
        setState(() {
          state = next;
          loading = false;
          if (!silent) error = null;
        });
      }
    } catch (e) {
      if (mounted && !silent) {
        setState(() {
          loading = false;
          error = message(e);
        });
      }
    } finally {
      reading = false;
    }
  }

  String message(Object e) => e is PlatformException
      ? e.message ?? 'Clock could not complete this action.'
      : e.toString();
  Future<void> act(
    String action, [
    Map<String, dynamic> args = const {},
  ]) async {
    if (busy) return;
    setState(() => busy = true);
    try {
      final next = await service.execute(action, args);
      if (mounted) {
        setState(() {
          state = next;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(message(e))));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  List<Map<String, dynamic>> rows(String key) => (state[key] as List? ?? [])
      .map((e) => Map<String, dynamic>.from(e as Map))
      .toList();
  Map<String, dynamic> get settings =>
      Map<String, dynamic>.from(state['settings'] as Map? ?? {});
  @override
  Widget build(BuildContext context) {
    final permissions = state['permissions'] as Map? ?? {};
    return Scaffold(
      appBar: AppBar(
        title: const Text('Jarvis Clock'),
        actions: [
          IconButton(
            tooltip: 'Clock settings',
            onPressed: clockSettings,
            icon: const Icon(Icons.tune),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 840),
            child: Column(
              children: [
                if (busy) const LinearProgressIndicator(minHeight: 2),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.all(20),
                    child: Text(
                      error!,
                      style: const TextStyle(color: AppTheme.red),
                    ),
                  ),
                if (state.isNotEmpty &&
                    (permissions['exact'] != true ||
                        permissions['notifications'] != true ||
                        permissions['fullScreen'] != true))
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 6,
                    ),
                    child: Material(
                      color: AppTheme.primarySurface,
                      borderRadius: BorderRadius.circular(16),
                      child: ListTile(
                        leading: const Icon(
                          Icons.notifications_active_outlined,
                        ),
                        title: const Text('Set up reliable ringing'),
                        subtitle: const Text(
                          'Review alarm, notification and lock-screen permissions',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: permissionSheet,
                      ),
                    ),
                  ),
                Expanded(
                  child: loading
                      ? const Center(child: CircularProgressIndicator())
                      : switch (tab) {
                          0 => alarms(),
                          1 => worlds(),
                          2 => timers(),
                          3 => stopwatch(),
                          _ => bedtime(),
                        },
                ),
              ],
            ),
          ),
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (v) => setState(() => tab = v),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.alarm_outlined),
            selectedIcon: Icon(Icons.alarm),
            label: 'Alarm',
          ),
          NavigationDestination(
            icon: Icon(Icons.public_outlined),
            selectedIcon: Icon(Icons.public),
            label: 'Clock',
          ),
          NavigationDestination(
            icon: Icon(Icons.timer_outlined),
            selectedIcon: Icon(Icons.timer),
            label: 'Timer',
          ),
          NavigationDestination(
            icon: Icon(Icons.av_timer_outlined),
            selectedIcon: Icon(Icons.av_timer),
            label: 'Stopwatch',
          ),
          NavigationDestination(
            icon: Icon(Icons.bedtime_outlined),
            selectedIcon: Icon(Icons.bedtime),
            label: 'Bedtime',
          ),
        ],
      ),
      floatingActionButton: tab == 0 || tab == 1 || tab == 2
          ? FloatingActionButton.extended(
              onPressed: busy
                  ? null
                  : () => switch (tab) {
                      0 => alarmEditor(),
                      1 => addCity(),
                      _ => timerEditor(),
                    },
              icon: const Icon(Icons.add),
              label: Text(switch (tab) {
                0 => 'Add alarm',
                1 => 'Add city',
                _ => 'New timer',
              }),
            )
          : null,
    );
  }

  Widget empty(IconData icon, String title, String body) => Padding(
    padding: const EdgeInsets.all(32),
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 64, color: AppTheme.primaryLight),
          const SizedBox(height: 24),
          Text(
            title,
            style: Theme.of(context).textTheme.headlineSmall,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 12),
          Text(
            body,
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppTheme.textSecondary),
          ),
        ],
      ),
    ),
  );
  String alarmTime(Map<String, dynamic> a) =>
      '${(a['hour'] as num? ?? 0).toInt().toString().padLeft(2, '0')}:${(a['minute'] as num? ?? 0).toInt().toString().padLeft(2, '0')}';
  String dayLabel(List days) {
    if (days.isEmpty) return 'Once';
    if (days.length == 7) return 'Every day';
    return days
        .map(
          (d) => const [
            'Mon',
            'Tue',
            'Wed',
            'Thu',
            'Fri',
            'Sat',
            'Sun',
          ][(d as num).toInt() - 1],
        )
        .join(' · ');
  }

  Widget alarms() {
    final items = rows('alarms')
      ..sort(
        (a, b) =>
            (a['nextAt'] as num? ?? 0).compareTo(b['nextAt'] as num? ?? 0),
      );
    if (items.isEmpty) {
      return empty(
        Icons.alarm,
        'Wake up your way',
        'Create a one-time or repeating alarm. Ringing works even when the assistant is off.',
      );
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 110),
      children: [
        const Padding(
          padding: EdgeInsets.only(bottom: 18),
          child: Text(
            'Your next beginning',
            style: TextStyle(color: AppTheme.textSecondary),
          ),
        ),
        for (final a in items)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: InkWell(
                          onTap: () => alarmEditor(a),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                alarmTime(a),
                                style: TextStyle(
                                  fontSize: 52,
                                  fontWeight: FontWeight.w300,
                                  color: a['enabled'] == true
                                      ? AppTheme.textPrimary
                                      : AppTheme.textSecondary,
                                ),
                              ),
                              Text(
                                a['label']?.toString() ?? 'Alarm',
                                style: const TextStyle(fontSize: 17),
                              ),
                            ],
                          ),
                        ),
                      ),
                      Switch(
                        value: a['enabled'] == true,
                        onChanged: busy
                            ? null
                            : (value) => act('alarm.toggle', {
                                'id': a['id'],
                                'enabled': value,
                              }),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    dayLabel(a['days'] as List? ?? []),
                    style: const TextStyle(color: AppTheme.primaryLight),
                  ),
                  if (a['enabled'] == true && a['nextAt'] is num)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text(
                        'In ${clockDuration(((a['nextAt'] as num).toInt() - DateTime.now().millisecondsSinceEpoch).clamp(0, 31536000000))}',
                        style: const TextStyle(color: AppTheme.textSecondary),
                      ),
                    ),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      if (a['ringing'] == true) ...[
                        TextButton(
                          onPressed: () => act('snooze', {'id': a['id']}),
                          child: const Text('Snooze'),
                        ),
                        FilledButton(
                          onPressed: () => act('dismiss', {'id': a['id']}),
                          child: const Text('Stop'),
                        ),
                      ] else if (a['enabled'] == true)
                        TextButton(
                          onPressed: () => act('alarm.skip', {'id': a['id']}),
                          child: const Text('Skip next'),
                        ),
                      IconButton(
                        tooltip: 'Edit alarm',
                        onPressed: () => alarmEditor(a),
                        icon: const Icon(Icons.edit_outlined),
                      ),
                      IconButton(
                        tooltip: 'Delete alarm',
                        onPressed: () => confirmDelete(a),
                        icon: const Icon(Icons.delete_outline),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  Future<void> confirmDelete(Map<String, dynamic> item) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Delete ${item['label'] ?? 'clock item'}?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (yes == true) await act('delete', {'id': item['id']});
  }

  Future<void> alarmEditor([Map<String, dynamic>? alarm]) async {
    var time = TimeOfDay(
      hour: (alarm?['hour'] as num?)?.toInt() ?? 7,
      minute: (alarm?['minute'] as num?)?.toInt() ?? 0,
    );
    final label = TextEditingController(
      text: alarm?['label']?.toString() ?? '',
    );
    final days = Set<int>.from(alarm?['days'] as List? ?? []);
    var vibrate = alarm?['vibrate'] != false;
    var sound = alarm?['sound']?.toString() ?? '';
    if (!mounted) return;
    final value = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => Padding(
          padding: EdgeInsets.fromLTRB(
            24,
            8,
            24,
            MediaQuery.viewInsetsOf(c).bottom + 24,
          ),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  alarm == null ? 'New alarm' : 'Edit alarm',
                  style: Theme.of(c).textTheme.headlineSmall,
                ),
                const SizedBox(height: 16),
                OutlinedButton(
                  onPressed: () async {
                    final picked = await showTimePicker(
                      context: c,
                      initialTime: time,
                    );
                    if (picked != null) set(() => time = picked);
                  },
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text(
                      time.format(c),
                      style: const TextStyle(fontSize: 42),
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: label,
                  maxLength: 120,
                  decoration: const InputDecoration(
                    labelText: 'Label',
                    hintText: 'Morning walk',
                  ),
                ),
                const Text('Repeat'),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  children: [
                    for (var i = 1; i <= 7; i++)
                      FilterChip(
                        label: Text(
                          const ['M', 'T', 'W', 'T', 'F', 'S', 'S'][i - 1],
                        ),
                        selected: days.contains(i),
                        onSelected: (selected) =>
                            set(() => selected ? days.add(i) : days.remove(i)),
                      ),
                  ],
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Vibrate'),
                  value: vibrate,
                  onChanged: (v) => set(() => vibrate = v),
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.music_note_outlined),
                  title: const Text('Alarm sound'),
                  subtitle: Text(
                    sound == 'silent'
                        ? 'Silent'
                        : sound.isEmpty
                        ? 'Default alarm sound'
                        : 'Custom sound selected',
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () async {
                    final selected = await service.pickSound();
                    if (selected != null) set(() => sound = selected);
                  },
                ),
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: () => Navigator.pop(c, {
                    'id': ?alarm?['id'],
                    'hour': time.hour,
                    'minute': time.minute,
                    'days': days.toList()..sort(),
                    'label': label.text.trim().isEmpty
                        ? 'Alarm'
                        : label.text.trim(),
                    'vibrate': vibrate,
                    'sound': sound,
                    'enabled': true,
                  }),
                  child: const Text('Save alarm'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    label.dispose();
    if (value != null) await act('alarm.save', value);
  }

  Widget worlds() {
    final list = rows('worlds');
    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 12, 24, 110),
      children: [
        Text(
          state['localTime']?.toString() ?? '--:--',
          style: const TextStyle(fontSize: 56, fontWeight: FontWeight.w300),
        ),
        Text(
          state['localDate']?.toString() ?? '',
          style: const TextStyle(color: AppTheme.textSecondary),
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          onPressed: nightClock,
          icon: const Icon(Icons.nights_stay_outlined),
          label: const Text('Bedside display'),
        ),
        const SizedBox(height: 24),
        for (final w in list)
          Card(
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 20,
                vertical: 12,
              ),
              title: Text(
                w['city'].toString(),
                style: const TextStyle(fontSize: 20),
              ),
              subtitle: Text(
                '${w['date']} · UTC${w['offset']}\n${difference((w['differenceMinutes'] as num).toInt())}',
              ),
              isThreeLine: true,
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    w['time'].toString(),
                    style: const TextStyle(fontSize: 24),
                  ),
                  IconButton(
                    tooltip: 'Remove city',
                    onPressed: () => act('world.remove', {'zone': w['id']}),
                    icon: const Icon(Icons.close, size: 18),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  String difference(int minutes) => minutes == 0
      ? 'Same time'
      : '${minutes.abs() ~/ 60}h ${minutes.abs() % 60}m ${minutes > 0 ? 'ahead' : 'behind'}';
  Future<void> addCity() async {
    final data = await service.execute('zones');
    if (!mounted) return;
    final all = List<String>.from(data['zones'] as List);
    String query = '';
    final zone = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => SizedBox(
          height: MediaQuery.sizeOf(c).height * .8,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                TextField(
                  autofocus: true,
                  decoration: const InputDecoration(
                    prefixIcon: Icon(Icons.search),
                    hintText: 'Search city or time zone',
                  ),
                  onChanged: (v) =>
                      set(() => query = v.toLowerCase().replaceAll(' ', '_')),
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: ListView(
                    children: [
                      for (final id in all.where(
                        (id) => id.toLowerCase().contains(query),
                      ))
                        ListTile(
                          title: Text(id.replaceAll('_', ' ')),
                          onTap: () => Navigator.pop(c, id),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    if (zone != null) await act('world.add', {'zone': zone});
  }

  Widget timers() {
    final list = rows('timers');
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 110),
      children: [
        Wrap(
          spacing: 8,
          children: [
            for (final m in [1, 5, 10, 25])
              ActionChip(
                label: Text('$m min'),
                onPressed: () => act('timer.start', {
                  'seconds': m * 60,
                  'label': '$m-minute timer',
                }),
              ),
          ],
        ),
        if (list.isEmpty)
          SizedBox(
            height: 340,
            child: empty(
              Icons.hourglass_empty,
              'Make time for something',
              'Start several named timers. Pause, resume, reset or add a minute whenever you need.',
            ),
          ),
        for (final t in list)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          t['label']?.toString() ?? 'Timer',
                          style: const TextStyle(fontSize: 20),
                        ),
                      ),
                      IconButton(
                        tooltip: 'Delete timer',
                        onPressed: () => confirmDelete(t),
                        icon: const Icon(Icons.delete_outline),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    height: 170,
                    width: 170,
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        SizedBox.expand(
                          child: CircularProgressIndicator(
                            value:
                                ((t['remaining'] as num? ?? 0) /
                                        (t['duration'] as num? ?? 1))
                                    .clamp(0.0, 1.0),
                            strokeWidth: 6,
                            backgroundColor: AppTheme.border,
                          ),
                        ),
                        Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              clockDuration(
                                (t['remaining'] as num? ?? 0).toInt(),
                              ),
                              style: const TextStyle(
                                fontSize: 30,
                                fontFeatures: [FontFeature.tabularFigures()],
                              ),
                            ),
                            Text(
                              t['status'].toString(),
                              style: const TextStyle(
                                color: AppTheme.textSecondary,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 8,
                    alignment: WrapAlignment.center,
                    children: [
                      if (t['status'] == 'ringing')
                        FilledButton(
                          onPressed: () => act('dismiss', {'id': t['id']}),
                          child: const Text('Stop ringing'),
                        )
                      else
                        FilledButton.icon(
                          onPressed: () => act(
                            t['status'] == 'running'
                                ? 'timer.pause'
                                : 'timer.resume',
                            {'id': t['id']},
                          ),
                          icon: Icon(
                            t['status'] == 'running'
                                ? Icons.pause
                                : Icons.play_arrow,
                          ),
                          label: Text(
                            t['status'] == 'running'
                                ? 'Pause'
                                : t['status'] == 'paused'
                                ? 'Resume'
                                : 'Start',
                          ),
                        ),
                      OutlinedButton(
                        onPressed: () =>
                            act('timer.add', {'id': t['id'], 'seconds': 60}),
                        child: const Text('+1:00'),
                      ),
                      IconButton(
                        tooltip: 'Reset timer',
                        onPressed: () => act('timer.reset', {'id': t['id']}),
                        icon: const Icon(Icons.restart_alt),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  Future<void> timerEditor() async {
    final hours = TextEditingController(text: '0'),
        minutes = TextEditingController(text: '5'),
        seconds = TextEditingController(text: '0'),
        label = TextEditingController();
    String? validation;
    final value = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('New timer'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: label,
                  maxLength: 120,
                  decoration: const InputDecoration(
                    labelText: 'Label',
                    hintText: 'Tea, focus, exercise…',
                  ),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    for (final pair in [
                      (hours, 'Hours'),
                      (minutes, 'Minutes'),
                      (seconds, 'Seconds'),
                    ])
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.all(4),
                          child: TextField(
                            controller: pair.$1,
                            keyboardType: TextInputType.number,
                            inputFormatters: [
                              FilteringTextInputFormatter.digitsOnly,
                            ],
                            decoration: InputDecoration(labelText: pair.$2),
                          ),
                        ),
                      ),
                  ],
                ),
                if (validation != null)
                  Text(
                    validation!,
                    style: const TextStyle(color: AppTheme.red),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () {
                final h = int.tryParse(hours.text) ?? 0,
                    m = int.tryParse(minutes.text) ?? 0,
                    s = int.tryParse(seconds.text) ?? 0;
                final total = h * 3600 + m * 60 + s;
                if (total < 1 || total > 31536000) {
                  set(
                    () => validation =
                        'Choose at least one second, up to one year.',
                  );
                  return;
                }
                Navigator.pop(c, {
                  'seconds': total,
                  'label': label.text.trim().isEmpty
                      ? 'Timer'
                      : label.text.trim(),
                });
              },
              child: const Text('Start'),
            ),
          ],
        ),
      ),
    );
    for (final c in [hours, minutes, seconds, label]) {
      c.dispose();
    }
    if (value != null) await act('timer.start', value);
  }

  Widget stopwatch() {
    final sw = Map<String, dynamic>.from(state['stopwatch'] as Map? ?? {});
    final elapsed = (sw['displayElapsed'] as num? ?? 0).toInt();
    final laps = List<num>.from(sw['laps'] as List? ?? []);
    return Column(
      children: [
        const Spacer(),
        Text(
          clockDuration(elapsed, hundredths: true),
          style: const TextStyle(
            fontSize: 48,
            fontWeight: FontWeight.w300,
            fontFeatures: [FontFeature.tabularFigures()],
          ),
        ),
        const SizedBox(height: 32),
        Wrap(
          spacing: 16,
          alignment: WrapAlignment.center,
          children: [
            OutlinedButton(
              onPressed: () => act(
                sw['running'] == true ? 'stopwatch.lap' : 'stopwatch.reset',
              ),
              child: Text(sw['running'] == true ? 'Lap' : 'Reset'),
            ),
            FilledButton.icon(
              onPressed: () => act(
                sw['running'] == true ? 'stopwatch.pause' : 'stopwatch.start',
              ),
              icon: Icon(
                sw['running'] == true ? Icons.pause : Icons.play_arrow,
              ),
              label: Text(sw['running'] == true ? 'Pause' : 'Start'),
            ),
            IconButton(
              tooltip: 'Share laps',
              onPressed: () async {
                await SharePlus.instance.share(
                  ShareParams(
                    text:
                        'Jarvis stopwatch: ${clockDuration(elapsed, hundredths: true)}\n${[for (var i = 0; i < laps.length; i++) 'Lap ${i + 1}: ${clockDuration(laps[i].toInt() - (i == 0 ? 0 : laps[i - 1].toInt()), hundredths: true)} — ${clockDuration(laps[i].toInt(), hundredths: true)}'].join('\n')}',
                  ),
                );
              },
              icon: const Icon(Icons.share_outlined),
            ),
          ],
        ),
        const Spacer(),
        Expanded(
          flex: 4,
          child: ListView(
            children: [
              for (var i = laps.length - 1; i >= 0; i--)
                ListTile(
                  leading: Text('${i + 1}'),
                  title: Text(
                    clockDuration(
                      laps[i].toInt() - (i == 0 ? 0 : laps[i - 1].toInt()),
                      hundredths: true,
                    ),
                  ),
                  trailing: Text(
                    clockDuration(laps[i].toInt(), hundredths: true),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget bedtime() {
    final b = Map<String, dynamic>.from(state['bedtime'] as Map? ?? {});
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const Icon(
          Icons.bedtime_outlined,
          size: 58,
          color: AppTheme.primaryLight,
        ),
        const SizedBox(height: 20),
        Text(
          'A gentler end to your day',
          style: Theme.of(context).textTheme.headlineSmall,
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 12),
        const Text(
          'Set a wind-down reminder and a wake-up alarm. Your schedule runs on this phone.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppTheme.textSecondary),
        ),
        const SizedBox(height: 24),
        Card(
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.nightlight_outlined),
                title: const Text('Bedtime'),
                trailing: Text(
                  '${(b['bedHour'] ?? 22).toString().padLeft(2, '0')}:${(b['bedMinute'] ?? 0).toString().padLeft(2, '0')}',
                ),
              ),
              ListTile(
                leading: const Icon(Icons.wb_sunny_outlined),
                title: const Text('Wake up'),
                trailing: Text(
                  '${(b['wakeHour'] ?? 7).toString().padLeft(2, '0')}:${(b['wakeMinute'] ?? 0).toString().padLeft(2, '0')}',
                ),
              ),
              SwitchListTile(
                title: const Text('Bedtime schedule'),
                value: b['enabled'] == true,
                onChanged: (v) => bedtimeEditor(enabled: v),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        FilledButton.tonal(
          onPressed: bedtimeEditor,
          child: const Text('Edit schedule'),
        ),
        const SizedBox(height: 28),
        Text('Sleep sounds', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        for (final sound in [
          ('rain', 'Rain', Icons.water_drop_outlined),
          ('ocean', 'Ocean', Icons.waves),
          ('brown', 'Brown noise', Icons.graphic_eq),
        ])
          Card(
            child: ListTile(
              leading: Icon(sound.$3),
              title: Text(sound.$2),
              subtitle: const Text(
                'Original offline sound · 30-minute sleep timer',
              ),
              trailing: IconButton(
                tooltip: 'Play ${sound.$2}',
                icon: const Icon(Icons.play_arrow),
                onPressed: () async {
                  try {
                    await service.sleep(sound.$1, 30);
                    if (mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text('${sound.$2} playing for 30 minutes'),
                        ),
                      );
                    }
                  } catch (e) {
                    if (mounted) {
                      ScaffoldMessenger.of(
                        context,
                      ).showSnackBar(SnackBar(content: Text(message(e))));
                    }
                  }
                },
              ),
            ),
          ),
        TextButton.icon(
          onPressed: () => service.sleep('rain', 30, stop: true),
          icon: const Icon(Icons.stop),
          label: const Text('Stop sleep sounds'),
        ),
        ListTile(
          leading: const Icon(Icons.do_not_disturb_on_outlined),
          title: const Text('Do Not Disturb settings'),
          subtitle: const Text('Manage quiet hours in Android'),
          trailing: const Icon(Icons.open_in_new),
          onTap: () => service.permissions('dnd'),
        ),
      ],
    );
  }

  Future<void> bedtimeEditor({bool? enabled}) async {
    final b = Map<String, dynamic>.from(state['bedtime'] as Map? ?? {});
    var bed = TimeOfDay(
          hour: (b['bedHour'] as num?)?.toInt() ?? 22,
          minute: (b['bedMinute'] as num?)?.toInt() ?? 0,
        ),
        wake = TimeOfDay(
          hour: (b['wakeHour'] as num?)?.toInt() ?? 7,
          minute: (b['wakeMinute'] as num?)?.toInt() ?? 0,
        );
    final days = Set<int>.from(b['days'] as List? ?? [1, 2, 3, 4, 5, 6, 7]);
    if (enabled != null) {
      await act('bedtime.save', {
        'bedHour': bed.hour,
        'bedMinute': bed.minute,
        'wakeHour': wake.hour,
        'wakeMinute': wake.minute,
        'days': days.toList(),
        'enabled': enabled,
      });
      return;
    }
    final result = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('Bedtime schedule'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                title: const Text('Wind down'),
                trailing: Text(bed.format(c)),
                onTap: () async {
                  final t = await showTimePicker(context: c, initialTime: bed);
                  if (t != null) set(() => bed = t);
                },
              ),
              ListTile(
                title: const Text('Wake up'),
                trailing: Text(wake.format(c)),
                onTap: () async {
                  final t = await showTimePicker(context: c, initialTime: wake);
                  if (t != null) set(() => wake = t);
                },
              ),
              Wrap(
                spacing: 4,
                children: [
                  for (var i = 1; i <= 7; i++)
                    FilterChip(
                      label: Text(
                        const ['M', 'T', 'W', 'T', 'F', 'S', 'S'][i - 1],
                      ),
                      selected: days.contains(i),
                      onSelected: (v) =>
                          set(() => v ? days.add(i) : days.remove(i)),
                    ),
                ],
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: days.isEmpty ? null : () => Navigator.pop(c, true),
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (result == true) {
      await act('bedtime.save', {
        'bedHour': bed.hour,
        'bedMinute': bed.minute,
        'wakeHour': wake.hour,
        'wakeMinute': wake.minute,
        'days': days.toList()..sort(),
        'enabled': true,
      });
    }
  }

  Future<void> permissionSheet() async {
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (c) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Clock permissions', style: Theme.of(c).textTheme.titleLarge),
            for (final entry in [
              ('exact', 'Alarms & reminders'),
              ('notifications', 'Notifications'),
              ('fullScreen', 'Full-screen alarm alerts'),
            ])
              ListTile(
                title: Text(entry.$2),
                trailing: Icon(
                  (state['permissions'] as Map?)?[entry.$1] == true
                      ? Icons.check_circle_outline
                      : Icons.open_in_new,
                ),
                onTap: () => service.permissions(entry.$1),
              ),
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text(
                'Android controls these permissions. Exact alarms and notifications are required to start timers and alarms.',
              ),
            ),
          ],
        ),
      ),
    );
    await refresh();
  }

  Future<void> clockSettings() async {
    final s = settings;
    double volume = (s['volume'] as num? ?? 1).toDouble();
    bool gradual = s['gradual'] == true;
    int snooze = (s['snoozeMinutes'] as num? ?? 10).toInt(),
        silence = (s['silenceMinutes'] as num? ?? 10).toInt();
    String volumeAction = s['volumeAction']?.toString() ?? 'snooze';
    String sound = s['sound']?.toString() ?? '';
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => Padding(
          padding: const EdgeInsets.all(24),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'Clock settings',
                  style: Theme.of(c).textTheme.headlineSmall,
                ),
                const SizedBox(height: 20),
                Text('Clock volume · ${(volume * 100).round()}%'),
                Slider(value: volume, onChanged: (v) => set(() => volume = v)),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Gradually increase volume'),
                  value: gradual,
                  onChanged: (v) => set(() => gradual = v),
                ),
                DropdownButtonFormField<int>(
                  initialValue: snooze,
                  decoration: const InputDecoration(
                    labelText: 'Snooze duration',
                  ),
                  items: [
                    for (final i in {
                      1,
                      5,
                      10,
                      15,
                      20,
                      30,
                      60,
                      snooze,
                    }.toList()..sort())
                      DropdownMenuItem(value: i, child: Text('$i minutes')),
                  ],
                  onChanged: (v) => set(() => snooze = v!),
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<int>(
                  initialValue: silence,
                  decoration: const InputDecoration(
                    labelText: 'Silence ringing after',
                  ),
                  items: [
                    for (final i in {
                      1,
                      5,
                      10,
                      15,
                      20,
                      30,
                      60,
                      silence,
                    }.toList()..sort())
                      DropdownMenuItem(value: i, child: Text('$i minutes')),
                  ],
                  onChanged: (v) => set(() => silence = v!),
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<String>(
                  initialValue: volumeAction,
                  decoration: const InputDecoration(
                    labelText: 'Volume button action',
                  ),
                  items: [
                    for (final action in ['snooze', 'dismiss', 'none'])
                      DropdownMenuItem(value: action, child: Text(action)),
                  ],
                  onChanged: (v) => set(() => volumeAction = v!),
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Default alarm & timer sound'),
                  subtitle: Text(
                    sound == 'silent'
                        ? 'Silent'
                        : sound.isEmpty
                        ? 'System alarm sound'
                        : 'Custom sound',
                  ),
                  trailing: const Icon(Icons.music_note_outlined),
                  onTap: () async {
                    final v = await service.pickSound();
                    if (v != null) set(() => sound = v);
                  },
                ),
                TextButton(
                  onPressed: permissionSheet,
                  child: const Text('Alarm permissions'),
                ),
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: () => Navigator.pop(c, true),
                  child: const Text('Save settings'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    if (saved == true) {
      await act('settings.save', {
        'volume': volume,
        'gradual': gradual,
        'snoozeMinutes': snooze,
        'silenceMinutes': silence,
        'volumeAction': volumeAction,
        'sound': sound,
      });
    }
  }

  Future<void> nightClock() async {
    await Navigator.of(
      context,
    ).push(MaterialPageRoute<void>(builder: (_) => const _BedsideClock()));
  }
}

class _BedsideClock extends StatefulWidget {
  const _BedsideClock();
  @override
  State<_BedsideClock> createState() => _BedsideClockState();
}

class _BedsideClockState extends State<_BedsideClock> {
  Timer? ticker;
  DateTime now = DateTime.now();
  @override
  void initState() {
    super.initState();
    WakelockPlus.enable();
    ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => now = DateTime.now());
    });
  }

  @override
  void dispose() {
    ticker?.cancel();
    WakelockPlus.disable();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: Colors.black,
    body: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => Navigator.pop(context),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}',
              style: const TextStyle(
                fontSize: 84,
                fontWeight: FontWeight.w200,
                color: Color(0xFFB58450),
              ),
            ),
            const SizedBox(height: 20),
            const Text('Tap to return', style: TextStyle(color: Colors.grey)),
          ],
        ),
      ),
    ),
  );
}
