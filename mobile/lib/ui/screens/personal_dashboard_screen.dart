import 'dart:convert';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../services/usage_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';
import 'activity_screen.dart';

class PersonalDashboardScreen extends StatefulWidget {
  const PersonalDashboardScreen({super.key, this.load});
  final Future<Map<String, dynamic>> Function(String day)? load;

  @override
  State<PersonalDashboardScreen> createState() =>
      _PersonalDashboardScreenState();
}

class _PersonalDashboardScreenState extends State<PersonalDashboardScreen>
    with WidgetsBindingObserver {
  Timer? _refreshTimer;
  bool _resumed = true;
  DateTime _day = DateTime.now().toUtc().add(
    const Duration(hours: 5, minutes: 30),
  );
  Map<String, dynamic>? _phone;
  String? _phoneError;
  bool _loading = false;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _refresh();
    if (widget.load == null) {
      WidgetsBinding.instance.addObserver(this);
      _refreshTimer = Timer.periodic(const Duration(minutes: 1), (_) {
        if (mounted &&
            _resumed &&
            !_loading &&
            TickerMode.getValuesNotifier(context).value.enabled) {
          _refresh();
        }
      });
    }
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _resumed = state == AppLifecycleState.resumed;
    if (_resumed &&
        !_loading &&
        TickerMode.getValuesNotifier(context).value.enabled) {
      _refresh();
    }
  }

  Future<void> _refresh() async {
    final generation = ++_generation;
    setState(() => _loading = true);
    final day = DateFormat('yyyy-MM-dd').format(_day);
    Map<String, dynamic>? phone;
    String? phoneError;
    try {
      if (widget.load != null) {
        final data = await widget.load!(day);
        phone = data['phone'] as Map<String, dynamic>?;
      } else {
        try {
          phone =
              jsonDecode(
                    await UsageService.channel.invokeMethod<String>(
                          'read',
                          day,
                        ) ??
                        '{}',
                  )
                  as Map<String, dynamic>;
          if (phone['error'] != null) {
            phoneError = UsageService.errorText(phone['error']?.toString());
          }
        } catch (_) {
          phoneError = UsageService.errorText(null);
        }
      }
    } catch (_) {
      phoneError = 'Activity could not load. Pull down to retry.';
    }
    if (!mounted || generation != _generation) return;
    setState(() {
      _phone = phone;
      _phoneError = phoneError;
      _loading = false;
    });
  }

  void _changeDay(int offset) {
    final today = DateTime.now().toUtc().add(
      const Duration(hours: 5, minutes: 30),
    );
    final next = _day.add(Duration(days: offset));
    if (DateFormat(
              'yyyy-MM-dd',
            ).format(next).compareTo(DateFormat('yyyy-MM-dd').format(today)) >
            0 ||
        today.difference(next).inDays > 29) {
      return;
    }
    setState(() {
      _day = next;
      _phone = null;
    });
    _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final phoneApps = List<Map<String, dynamic>>.from(_phone?['apps'] ?? []);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Overview'),
        actions: [
          IconButton(
            tooltip: 'Refresh activity',
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loading ? null : _refresh,
          ),
        ],
      ),
      body: WorkspaceBody(
        child: RefreshIndicator(
          onRefresh: _refresh,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 40),
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: FilledButton.icon(
                  icon: const Icon(Icons.route_outlined),
                  label: const Text('Activity'),
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => const ActivityScreen(),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 20),
              const PageIntro(
                title: 'Your day, in focus.',
                description: 'Your Android activity, stored on this phone.',
              ),
              Row(
                children: [
                  IconButton(
                    tooltip: 'Previous day',
                    onPressed: () => _changeDay(-1),
                    icon: const Icon(Icons.chevron_left),
                  ),
                  Expanded(
                    child: Text(
                      DateFormat('EEE, dd MMM').format(_day),
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                  const Text(
                    'IST',
                    style: TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 11,
                    ),
                  ),
                  IconButton(
                    tooltip: 'Next day',
                    onPressed: () => _changeDay(1),
                    icon: const Icon(Icons.chevron_right),
                  ),
                ],
              ),
              if (_loading)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: LinearProgressIndicator(minHeight: 2),
                ),
              const SizedBox(height: 16),
              _total(
                'ANDROID',
                'Screen time',
                _phone != null && _phoneError == null
                    ? UsageService.duration(_phone!['total_ms'] as num? ?? 0)
                    : '—',
                Icons.phone_android_outlined,
              ),
              const SizedBox(height: 20),
              _apps(
                'On your phone',
                'Android · foreground app time',
                phoneApps,
                _phoneError ?? 'No Android app records for this day.',
              ),
              const SizedBox(height: 16),
              const Text(
                'App usage and recordings stay on this phone. Android totals use foreground activity events.',
                style: TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 12,
                  height: 1.5,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _total(
    String platform,
    String label,
    String value,
    IconData icon,
  ) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: AppTheme.surface,
      borderRadius: BorderRadius.circular(AppTheme.radius),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(
              icon,
              size: 20,
              color: platform == 'ANDROID' ? AppTheme.green : AppTheme.primary,
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                platform,
                style: const TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 10,
                  letterSpacing: 1,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 18),
        Text(
          value,
          style: const TextStyle(
            fontSize: 27,
            fontWeight: FontWeight.w600,
            letterSpacing: -0.8,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          label,
          style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
        ),
      ],
    ),
  );

  Widget _apps(
    String title,
    String source,
    List<Map<String, dynamic>> apps,
    String empty,
  ) {
    final sorted = [...apps]
      ..sort(
        (a, b) =>
            (b['milliseconds'] as num).compareTo(a['milliseconds'] as num),
      );
    final maximum = sorted.isEmpty
        ? 1
        : (sorted.first['milliseconds'] as num).clamp(1, double.infinity);
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 7),
          Text(
            source,
            style: const TextStyle(color: AppTheme.textSecondary, fontSize: 11),
          ),
          const SizedBox(height: 20),
          if (sorted.isEmpty)
            Text(
              empty,
              style: const TextStyle(
                color: AppTheme.textSecondary,
                height: 1.5,
              ),
            ),
          for (final app in sorted)
            Padding(
              padding: const EdgeInsets.only(bottom: 18),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          app['name']?.toString() ?? app['package'].toString(),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Text(
                        UsageService.duration(app['milliseconds'] as num),
                        style: const TextStyle(
                          color: AppTheme.textSecondary,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 9),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      value: ((app['milliseconds'] as num) / maximum)
                          .clamp(0, 1)
                          .toDouble(),
                      minHeight: 4,
                      color: source.startsWith('Android')
                          ? AppTheme.green
                          : AppTheme.primary,
                      backgroundColor: AppTheme.surfaceBright,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
