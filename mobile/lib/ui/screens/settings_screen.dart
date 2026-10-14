import '../widgets/database_backup_settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../brand_colors.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';
import 'google_calendar_screen.dart';
import 'google_drive_screen.dart';
import '../../services/google_calendar_service.dart';
import '../../services/google_drive_service.dart';
import '../../services/runtime_power_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  final _power = RuntimePowerService.instance;
  late final AnimationController _pulseController;
  late final Animation<double> _pulseAnimation;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _power.addListener(_onStateChanged);
    GoogleCalendarService.instance.addListener(_onStateChanged);
    GoogleCalendarService.instance.refresh();
    GoogleDriveService.instance.addListener(_onStateChanged);
    GoogleDriveService.instance.refresh();

    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2200),
    )..repeat(reverse: true);

    _pulseAnimation = CurvedAnimation(
      parent: _pulseController,
      curve: Curves.easeInOutSine,
    );
  }

  void _onStateChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pulseController.dispose();
    _power.removeListener(_onStateChanged);
    GoogleCalendarService.instance.removeListener(_onStateChanged);
    GoogleDriveService.instance.removeListener(_onStateChanged);
    super.dispose();
  }

  bool get _hasConnectedAccounts =>
      GoogleCalendarService.instance.connected ||
      GoogleDriveService.instance.connected;

  void _showConnectedAccounts(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppTheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        side: BorderSide(color: AppTheme.border),
      ),
      builder: (ctx) {
        final cal = GoogleCalendarService.instance;
        final drive = GoogleDriveService.instance;
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 36,
                    height: 4,
                    margin: const EdgeInsets.only(bottom: 20),
                    decoration: BoxDecoration(
                      color: AppTheme.border,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16),
                  child: Text(
                    'Connected Accounts',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w600,
                      letterSpacing: -0.4,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ),
                const SizedBox(height: 6),
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16),
                  child: Text(
                    'Manage your cloud Google services.',
                    style: TextStyle(
                      fontSize: 13,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ),
                const SizedBox(height: 18),
                ListTile(
                  leading: Icon(
                    cal.connected
                        ? Icons.check_circle_outline
                        : Icons.calendar_month_outlined,
                    color: cal.connected ? AppTheme.green : AppTheme.primaryLight,
                  ),
                  title: const Text('Google Calendar'),
                  subtitle: Text(
                    cal.connected
                        ? 'Connected · ${cal.email}'
                        : (cal.needsReconnect
                            ? 'Reconnect needed'
                            : 'Not connected'),
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () {
                    Navigator.pop(ctx);
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => const GoogleCalendarScreen(),
                      ),
                    );
                  },
                ),
                const Divider(height: 1, color: AppTheme.border),
                ListTile(
                  leading: Icon(
                    drive.connected
                        ? Icons.check_circle_outline
                        : Icons.add_to_drive_outlined,
                    color: drive.connected ? AppTheme.green : AppTheme.primaryLight,
                  ),
                  title: const Text('Google Drive'),
                  subtitle: Text(
                    drive.connected
                        ? 'Connected · ${drive.email}'
                        : (drive.needsReconnect
                            ? 'Reconnect needed'
                            : 'Not connected'),
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () {
                    Navigator.pop(ctx);
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => const GoogleDriveScreen(),
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _handlePowerToggle() {
    if (_power.busy) return;
    HapticFeedback.heavyImpact();
    _power.setEnabled(!_power.enabled);
  }

  @override
  Widget build(BuildContext context) {
    final enabled = _power.enabled;
    final busy = _power.busy;

    // Vibrant hero palette: Emerald Green when ON, Crimson Red when OFF
    const onColor = Color(0xFF00E676);
    const onDark = Color(0xFF008947);
    const offColor = Color(0xFFFF3B30);
    const offDark = Color(0xFF8B1E18);

    final primaryColor = enabled ? onColor : offColor;
    final gradientDark = enabled ? onDark : offDark;

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text('Settings'),
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          IconButton(
            icon: Badge(
              isLabelVisible: _hasConnectedAccounts,
              backgroundColor: AppTheme.green,
              smallSize: 8,
              child: const Icon(Icons.cloud_outlined),
            ),
            tooltip: 'Connected Accounts',
            onPressed: () => _showConnectedAccounts(context),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: WorkspaceBody(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Top subtle header
                const Text(
                  'SYSTEM POWER',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 2.0,
                    color: AppTheme.textSecondary,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  enabled ? 'Jarvis is Active' : 'Jarvis is Powered Off',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.w600,
                    letterSpacing: -0.6,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 48),

                // Hero Interactive Power Button with Pulse Animation
                AnimatedBuilder(
                  animation: _pulseAnimation,
                  builder: (context, child) {
                    final pulse = enabled ? _pulseAnimation.value : 0.0;
                    final glowRadius = 24.0 + (pulse * 20.0);
                    final glowSpread = 2.0 + (pulse * 8.0);
                    final glowAlpha = enabled ? (0.28 + pulse * 0.18) : 0.20;

                    return AnimatedContainer(
                      duration: const Duration(milliseconds: 400),
                      curve: Curves.easeInOutCubicEmphasized,
                      width: 170,
                      height: 170,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        boxShadow: [
                          // Outer ambient bloom
                          BoxShadow(
                            color: primaryColor.withValues(alpha: glowAlpha),
                            blurRadius: glowRadius,
                            spreadRadius: glowSpread,
                          ),
                          // Secondary soft perimeter shadow
                          BoxShadow(
                            color: Colors.black.withValues(alpha: 0.5),
                            blurRadius: 18,
                            spreadRadius: 2,
                            offset: const Offset(0, 8),
                          ),
                        ],
                      ),
                      child: child,
                    );
                  },
                  child: Material(
                    color: Colors.transparent,
                    shape: const CircleBorder(),
                    clipBehavior: Clip.antiAlias,
                    child: InkWell(
                      onTap: busy ? null : _handlePowerToggle,
                      splashColor: primaryColor.withValues(alpha: 0.3),
                      highlightColor: primaryColor.withValues(alpha: 0.15),
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 400),
                        curve: Curves.easeInOutCubicEmphasized,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: RadialGradient(
                            center: const Alignment(-0.2, -0.3),
                            radius: 0.85,
                            colors: [
                              primaryColor,
                              gradientDark,
                              const Color(0xFF14171B),
                            ],
                            stops: const [0.0, 0.65, 1.0],
                          ),
                          border: Border.all(
                            color: primaryColor.withValues(alpha: 0.7),
                            width: 2.5,
                          ),
                        ),
                        child: Center(
                          child: busy
                              ? const SizedBox(
                                  width: 48,
                                  height: 48,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 3.5,
                                    valueColor: AlwaysStoppedAnimation<Color>(
                                      Colors.white,
                                    ),
                                  ),
                                )
                              : AnimatedRotation(
                                  turns: enabled ? 0.0 : 0.5,
                                  duration: const Duration(milliseconds: 450),
                                  curve: Curves.easeInOutBack,
                                  child: AnimatedScale(
                                    scale: enabled ? 1.05 : 0.95,
                                    duration: const Duration(milliseconds: 300),
                                    curve: Curves.easeOutBack,
                                    child: Icon(
                                      Icons.power_settings_new_rounded,
                                      size: 72,
                                      color: Colors.white.withValues(
                                        alpha: enabled ? 1.0 : 0.9,
                                      ),
                                      shadows: [
                                        Shadow(
                                          color: Colors.black.withValues(alpha: 0.6),
                                          blurRadius: 12,
                                          offset: const Offset(0, 4),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                        ),
                      ),
                    ),
                  ),
                ),

                const SizedBox(height: 48),

                // Animated Status Badge
                AnimatedContainer(
                  duration: const Duration(milliseconds: 350),
                  curve: Curves.easeInOut,
                  padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
                  decoration: BoxDecoration(
                    color: primaryColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(
                      color: primaryColor.withValues(alpha: 0.35),
                      width: 1,
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: primaryColor,
                          boxShadow: [
                            BoxShadow(
                              color: primaryColor.withValues(alpha: 0.8),
                              blurRadius: 6,
                              spreadRadius: 1,
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 10),
                      Text(
                        busy
                            ? 'UPDATING…'
                            : (enabled ? 'JARVIS ONLINE' : 'STANDBY MODE'),
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1.4,
                          color: primaryColor,
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 18),

                // Dynamic Status Explanation
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 300),
                  child: Text(
                    busy
                        ? 'Applying power change to phone background services…'
                        : enabled
                            ? 'Background monitoring, location awareness, and assistant features are active.'
                            : 'Phone services, sensor tracking, and automations are paused.\nTap the button to power on.',
                    key: ValueKey('$enabled-$busy'),
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 14,
                      height: 1.5,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ),

                if (_power.error != null) ...[
                  const SizedBox(height: 24),
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: BrandColors.red.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(AppTheme.radius),
                      border: Border.all(
                        color: BrandColors.red.withValues(alpha: 0.35),
                      ),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.error_outline, color: BrandColors.red, size: 20),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            _power.error!,
                            style: const TextStyle(
                              color: BrandColors.red,
                              fontSize: 13,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],

                const SizedBox(height: 48),

                const DatabaseBackupSettings(),
                const SizedBox(height: 24),

                // Bottom note indicating connected accounts icon
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      Icons.cloud_outlined,
                      size: 14,
                      color: AppTheme.textSecondary.withValues(alpha: 0.7),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      'Google Calendar & Drive accessible via top-right cloud icon',
                      style: TextStyle(
                        fontSize: 12,
                        color: AppTheme.textSecondary.withValues(alpha: 0.7),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

