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
  final PageController _pages = PageController(initialPage: 29);
  late DateTime _windowEnd = DateTime(_day.year, _day.month, _day.day);
  int _targetPage = 29;
  int _slideRequest = 0;
  bool _slidingByArrow = false;
  final Map<String, Map<String, dynamic>?> _loadedDays = {};
  String get _dayKey => DateFormat('yyyy-MM-dd').format(_day);

  @override
  void initState() {
    super.initState();
    if (widget.load == null) {
      UsageService.overviewDays.addListener(_showCachedDay);
      _showCachedDay();
      _openCache();
      WidgetsBinding.instance.addObserver(this);
      _refreshTimer = Timer.periodic(const Duration(minutes: 1), (_) {
        if (mounted &&
            _resumed &&
            !_loading &&
            TickerMode.getValuesNotifier(context).value.enabled) {
          _refresh();
        }
      });
    } else {
      _refresh();
    }
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    _pages.dispose();
    UsageService.overviewDays.removeListener(_showCachedDay);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  Future<void> _openCache() async {
    try {
      await UsageService.loadOverviewCache();
      if (!mounted) return;
      _showCachedDay();
      unawaited(_refresh());
    } catch (_) {
      if (mounted) setState(() => _phoneError = UsageService.errorText(null));
    }
  }

  void _showCachedDay() {
    if (!mounted) return;
    final phone = UsageService.overviewDays.value[_dayKey];
    setState(() {
      _phone = phone;
      _phoneError = phone?['error'] == null
          ? null
          : UsageService.errorText(phone!['error'].toString());
    });
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
    _rollDayWindow();
    final generation = ++_generation;
    setState(() => _loading = true);
    final day = _dayKey;
    Map<String, dynamic>? phone;
    String? phoneError;
    try {
      if (widget.load != null) {
        final data = await widget.load!(day);
        phone = data['phone'] as Map<String, dynamic>?;
        _loadedDays[day] = phone;
      } else {
        await UsageService.refreshOverviewCache();
        phone = UsageService.overviewDays.value[day];
      }
      if (phone?['error'] != null) {
        phoneError = UsageService.errorText(phone!['error'].toString());
      }
    } catch (_) {
      phone = _phone;
      phoneError = phone == null
          ? 'Activity could not load. Pull down to retry.'
          : _phoneError;
    }
    if (!mounted || generation != _generation) return;
    setState(() {
      _phone = phone;
      _phoneError = phoneError;
      _loading = false;
    });
  }

  void _rollDayWindow() {
    final now = DateTime.now().toUtc().add(
      const Duration(hours: 5, minutes: 30),
    );
    final today = DateTime(now.year, now.month, now.day);
    if (today == _windowEnd) return;
    final selected = DateTime(_day.year, _day.month, _day.day);
    final index = (29 - today.difference(selected).inDays).clamp(0, 29);
    setState(() {
      _windowEnd = today;
      _targetPage = index;
      _day = today.subtract(Duration(days: 29 - index));
      _phone = widget.load == null
          ? UsageService.overviewDays.value[_dayKey]
          : _loadedDays[_dayKey];
      _phoneError = _phone?['error'] == null
          ? null
          : UsageService.errorText(_phone!['error'].toString());
    });
    if (_pages.hasClients) _pages.jumpToPage(index);
  }

  void _changeDay(int offset) {
    final next = (_targetPage + offset).clamp(0, 29);
    if (next == _targetPage || !_pages.hasClients) return;
    _targetPage = next;
    final request = ++_slideRequest;
    _slidingByArrow = true;
    _pages
        .animateToPage(
          next,
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOutCubic,
        )
        .whenComplete(() {
          if (mounted && request == _slideRequest) _slidingByArrow = false;
        });
  }

  void _selectPage(int index) {
    final next = _windowEnd.subtract(Duration(days: 29 - index));
    if (!_slidingByArrow) _targetPage = index;
    setState(() {
      _day = next;
      ++_generation;
      _loading = false;
      _phoneError = null;
      _phone = widget.load == null
          ? UsageService.overviewDays.value[_dayKey]
          : _loadedDays[_dayKey];
      if (_phone?['error'] != null) {
        _phoneError = UsageService.errorText(_phone!['error'].toString());
      }
    });
    if (widget.load != null && !_loadedDays.containsKey(_dayKey)) _refresh();
  }

  @override
  Widget build(BuildContext context) {
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
        child: NotificationListener<ScrollStartNotification>(
          onNotification: (notification) {
            if (notification.metrics.axis == Axis.horizontal &&
                notification.dragDetails != null) {
              ++_slideRequest;
              _slidingByArrow = false;
              _targetPage = (_pages.page ?? 29).round();
            }
            return false;
          },
          child: PageView.builder(
            key: const ValueKey('overview-days'),
            controller: _pages,
            itemCount: 30,
            // Lay out the adjacent day before a swipe or arrow tap starts.
            allowImplicitScrolling: true,
            onPageChanged: _selectPage,
            itemBuilder: (context, index) {
              final day = _windowEnd.subtract(Duration(days: 29 - index));
              final key = DateFormat('yyyy-MM-dd').format(day);
              return _KeepOverviewDayAlive(
                key: ValueKey('overview-day-$key'),
                child: RepaintBoundary(child: _dayPage(day)),
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _dayPage(DateTime day) {
    final key = DateFormat('yyyy-MM-dd').format(day);
    final selected = key == _dayKey;
    final phone = selected
        ? _phone
        : widget.load == null
        ? UsageService.overviewDays.value[key]
        : _loadedDays[key];
    final phoneError = selected
        ? _phoneError
        : phone?['error'] == null
        ? null
        : UsageService.errorText(phone!['error'].toString());
    final phoneApps = List<Map<String, dynamic>>.from(phone?['apps'] ?? []);
    return ExcludeSemantics(
      excluding: !selected,
      child: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          key: PageStorageKey('overview-scroll-$key'),
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
                    DateFormat('EEE, dd MMM').format(day),
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
                const Text(
                  'IST',
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 11),
                ),
                IconButton(
                  tooltip: 'Next day',
                  onPressed: () => _changeDay(1),
                  icon: const Icon(Icons.chevron_right),
                ),
              ],
            ),
            SizedBox(
              height: 16,
              child: selected && _loading && phone == null
                  ? const Center(child: LinearProgressIndicator(minHeight: 2))
                  : null,
            ),
            _total(
              'ANDROID',
              'Screen time',
              phone != null && phoneError == null
                  ? UsageService.duration(phone['total_ms'] as num? ?? 0)
                  : '—',
              Icons.phone_android_outlined,
            ),
            const SizedBox(height: 20),
            _apps(
              'On your phone',
              'Android · top 5 apps by foreground time',
              phoneApps,
              phoneError ?? 'No Android app records for this day.',
            ),
            const SizedBox(height: 16),
            const Text(
              'Ask in chat for the full app breakdown. App usage and recordings stay on this phone.',
              style: TextStyle(
                color: AppTheme.textSecondary,
                fontSize: 12,
                height: 1.5,
              ),
            ),
          ],
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
          for (final app in sorted.take(5))
            Padding(
              key: ValueKey(app['package'] ?? app['name']),
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

class _KeepOverviewDayAlive extends StatefulWidget {
  const _KeepOverviewDayAlive({super.key, required this.child});
  final Widget child;

  @override
  State<_KeepOverviewDayAlive> createState() => _KeepOverviewDayAliveState();
}

class _KeepOverviewDayAliveState extends State<_KeepOverviewDayAlive>
    with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return widget.child;
  }
}
