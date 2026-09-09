import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/sensor_service.dart';
import '../theme.dart';

/// Agent HUD Screen:
/// Manages Stage 1 Google Activity Recognition Tripwire,
/// Cloud Run backend connectivity, and LangChain Agentic Commands (Reminders, Tasks, Notes).
class AgentScreen extends StatefulWidget {
  final SensorService sensorService;

  const AgentScreen({super.key, required this.sensorService});

  @override
  State<AgentScreen> createState() => _AgentScreenState();
}

class _AgentScreenState extends State<AgentScreen> {
  final ApiService _apiService = ApiService();
  final TextEditingController _commandController = TextEditingController();
  final TextEditingController _urlController = TextEditingController();

  bool _isSending = false;
  String? _lastJarvisResponse;
  String? _lastRunId;
  String? _lastError;

  final List<String> _quickCommands = [
    'Remind me to check tire pressure at Royal Enfield service garage',
    'Create high priority task to order chain lube due next Monday',
    'Note down: Odometer reading at start of journey was 4,285 km',
  ];

  @override
  void initState() {
    super.initState();
    _urlController.text = _apiService.baseUrl;
    _refreshData();
  }

  @override
  void dispose() {
    _commandController.dispose() ;
    _urlController.dispose();
    super.dispose();
  }

  Future<void> _refreshData() async {
    await _apiService.checkHealth();
    await _apiService.fetchReminders();
    await _apiService.fetchNotes();
    if (mounted) setState(() {});
  }

  Future<void> _sendCommand(String text) async {
    if (text.trim().isEmpty) return;

    setState(() {
      _isSending = true;
      _lastJarvisResponse = null;
      _lastError = null;
      _lastRunId = null;
    });

    final res = await _apiService.sendCommand(text.trim());

    if (mounted) {
      setState(() {
        _isSending = false;
        if (res != null && res['status'] == 'ok') {
          _lastJarvisResponse = res['message'] ?? 'Action executed successfully';
          _lastRunId = res['run_id'];
          _commandController.clear();
        } else {
          _lastError = res?['error'] ?? 'Failed to communicate with Cloud Run';
        }
      });
      await _refreshData();
    }
  }

  void _showEndpointDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.surfaceBright,
        title: const Text('Cloud Run Backend URL', style: TextStyle(color: AppTheme.textPrimary)),
        content: TextField(
          controller: _urlController,
          style: const TextStyle(color: AppTheme.textPrimary, fontSize: 13),
          decoration: const InputDecoration(
            hintText: 'https://jarvis-backend-xxx.a.run.app',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('CANCEL'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.primary),
            onPressed: () {
              _apiService.setBaseUrl(_urlController.text);
              Navigator.pop(ctx);
              _refreshData();
            },
            child: const Text('SAVE & CONNECT'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Row(
          children: [
            Icon(Icons.psychology, color: AppTheme.primary, size: 22),
            SizedBox(width: 8),
            Text(
              'JARVIS AGENT HUD',
              style: TextStyle(
                fontWeight: FontWeight.bold,
                letterSpacing: 1.2,
                fontSize: 15,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_ethernet, color: AppTheme.textSecondary),
            tooltip: 'Configure Backend URL',
            onPressed: _showEndpointDialog,
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: AppTheme.textSecondary),
            tooltip: 'Refresh Cloud Data',
            onPressed: _refreshData,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refreshData,
        backgroundColor: AppTheme.surfaceBright,
        color: AppTheme.primary,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // ── 1. Cloud & LangSmith Status Card ─────────────────────────────
            _buildCloudStatusCard(),
            const SizedBox(height: 14),

            // ── 2. Stage 1 Google Activity Recognition Tripwire ──────────────
            _buildTripwireCard(),
            const SizedBox(height: 14),

            // ── 3. Agent Command Input ───────────────────────────────────────
            _buildCommandInputCard(),
            const SizedBox(height: 14),

            // ── 4. Active Reminders (Tier 2 / CRUD Store) ───────────────────
            _buildRemindersSection(),
            const SizedBox(height: 14),

            // ── 5. Context Notes (Tier 2 / CRUD Store) ───────────────────────
            _buildNotesSection(),
          ],
        ),
      ),
    );
  }

  Widget _buildCloudStatusCard() {
    final isOnline = _apiService.isOnline;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isOnline ? AppTheme.green.withAlpha(80) : AppTheme.red.withAlpha(80),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Container(
                    width: 10,
                    height: 10,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: isOnline ? AppTheme.green : AppTheme.red,
                      boxShadow: [
                        BoxShadow(
                          color: (isOnline ? AppTheme.green : AppTheme.red).withAlpha(150),
                          blurRadius: 6,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    isOnline ? 'CLOUD RUN CONNECTED' : 'CONNECTING TO CLOUD RUN...',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.0,
                      color: isOnline ? AppTheme.green : AppTheme.red,
                    ),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppTheme.primary.withAlpha(30),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: AppTheme.primary.withAlpha(80)),
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.monitor_heart, color: AppTheme.primary, size: 12),
                    SizedBox(width: 4),
                    Text(
                      'LANGSMITH TRACED',
                      style: TextStyle(
                        fontSize: 9,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.primary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            _apiService.baseUrl,
            style: const TextStyle(
              fontSize: 11,
              fontFamily: 'monospace',
              color: AppTheme.textSecondary,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  Widget _buildTripwireCard() {
    final tripwireActive = widget.sensorService.isTripwireActive;
    final lastTransition = widget.sensorService.lastActivityTransition ?? 'DORMANT (Awaiting Vehicle Motion)';

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.surfaceBright),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Row(
                children: [
                  Icon(Icons.sensors, color: AppTheme.accent, size: 18),
                  SizedBox(width: 6),
                  Text(
                    'STAGE 1: GAR TRIPWIRE',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.0,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ],
              ),
              Switch(
                value: tripwireActive,
                activeThumbColor: AppTheme.primary,
                onChanged: (val) async {
                  if (val) {
                    await widget.sensorService.startTripwire();
                  } else {
                    await widget.sensorService.stopTripwire();
                  }
                  setState(() {});
                },
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Hardware state: $lastTransition',
            style: const TextStyle(
              fontSize: 11,
              fontFamily: 'monospace',
              color: AppTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppTheme.accent,
                    side: const BorderSide(color: AppTheme.accent),
                    padding: const EdgeInsets.symmetric(vertical: 8),
                  ),
                  icon: const Icon(Icons.flash_on, size: 16),
                  label: const Text(
                    'SIMULATE 10s BURST',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold),
                  ),
                  onPressed: widget.sensorService.isRecording
                      ? null
                      : () async {
                          await widget.sensorService.executeStage2Burst();
                          setState(() {});
                        },
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildCommandInputCard() {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.primary.withAlpha(60)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.mic, color: AppTheme.primary, size: 18),
              SizedBox(width: 6),
              Text(
                'NATURAL AGENT COMMAND (TIER 2)',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.0,
                  color: AppTheme.primary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _commandController,
            style: const TextStyle(color: AppTheme.textPrimary, fontSize: 13),
            maxLines: 2,
            decoration: InputDecoration(
              hintText: 'e.g. Remind me to check oil level at Royal Enfield service center',
              hintStyle: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
              filled: true,
              fillColor: AppTheme.surfaceBright,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide.none,
              ),
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final prompt in _quickCommands)
                ActionChip(
                  backgroundColor: AppTheme.surfaceBright,
                  label: Text(
                    prompt.split(':')[0].split('to')[0],
                    style: const TextStyle(fontSize: 10, color: AppTheme.textSecondary),
                  ),
                  onPressed: () {
                    _commandController.text = prompt;
                  },
                ),
            ],
          ),
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerRight,
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.primary,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              ),
              icon: _isSending
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.send, size: 16),
              label: const Text('DISPATCH COMMAND', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
              onPressed: _isSending ? null : () => _sendCommand(_commandController.text),
            ),
          ),
          if (_lastJarvisResponse != null) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppTheme.primary.withAlpha(25),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppTheme.primary.withAlpha(80)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.auto_awesome, color: AppTheme.primary, size: 14),
                      const SizedBox(width: 4),
                      const Text(
                        'JARVIS RESPONSE',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.primary,
                        ),
                      ),
                      if (_lastRunId != null) ...[
                        const Spacer(),
                        Text(
                          'Run: ${_lastRunId!.substring(0, 8)}...',
                          style: const TextStyle(fontSize: 9, color: AppTheme.textSecondary),
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _lastJarvisResponse!,
                    style: const TextStyle(fontSize: 12, color: AppTheme.textPrimary),
                  ),
                ],
              ),
            ),
          ],
          if (_lastError != null) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppTheme.red.withAlpha(25),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppTheme.red.withAlpha(80)),
              ),
              child: Text(
                _lastError!,
                style: const TextStyle(fontSize: 11, color: AppTheme.red),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildRemindersSection() {
    final reminders = _apiService.reminders;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.surfaceBright),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  const Icon(Icons.notifications_active, color: AppTheme.primary, size: 18),
                  const SizedBox(width: 6),
                  Text(
                    'ACTIVE REMINDERS (${reminders.length})',
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.0,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ],
              ),
              Text(
                'Synced with Cloud Run',
                style: TextStyle(fontSize: 10, color: AppTheme.textSecondary.withAlpha(150)),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (reminders.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text(
                'No active reminders. Send a command above to create one.',
                style: TextStyle(fontSize: 11, color: AppTheme.textSecondary),
              ),
            )
          else
            ListView.separated(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: reminders.length,
              separatorBuilder: (ctx, index) => const Divider(color: AppTheme.surfaceBright, height: 12),
              itemBuilder: (ctx, i) {
                final r = reminders[i];
                final title = r['title'] ?? r['body'] ?? 'Reminder';
                final loc = r['location_name'] ?? r['context_place'] ?? '';
                final due = r['due_time'] ?? '';

                return Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(6),
                      decoration: BoxDecoration(
                        color: AppTheme.primary.withAlpha(30),
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(Icons.alarm, color: AppTheme.primary, size: 14),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            title,
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          if (loc.isNotEmpty || due.isNotEmpty)
                            Text(
                              [if (loc.isNotEmpty) '📍 $loc', if (due.isNotEmpty) '⏰ $due'].join(' | '),
                              style: const TextStyle(fontSize: 10, color: AppTheme.accent),
                            ),
                        ],
                      ),
                    ),
                  ],
                );
              },
            ),
        ],
      ),
    );
  }

  Widget _buildNotesSection() {
    final notes = _apiService.notes;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.surfaceBright),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  const Icon(Icons.note_alt, color: AppTheme.accent, size: 18),
                  const SizedBox(width: 6),
                  Text(
                    'CONTEXT NOTES (${notes.length})',
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.0,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ],
              ),
              Text(
                'Stored in SQLite',
                style: TextStyle(fontSize: 10, color: AppTheme.textSecondary.withAlpha(150)),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (notes.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text(
                'No notes logged yet.',
                style: TextStyle(fontSize: 11, color: AppTheme.textSecondary),
              ),
            )
          else
            ListView.separated(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: notes.length,
              separatorBuilder: (ctx, index) => const Divider(color: AppTheme.surfaceBright, height: 12),
              itemBuilder: (ctx, i) {
                final n = notes[i];
                final content = n['content'] ?? '';
                final place = n['place'] ?? '';

                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      margin: const EdgeInsets.only(top: 2),
                      padding: const EdgeInsets.all(6),
                      decoration: BoxDecoration(
                        color: AppTheme.accent.withAlpha(30),
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(Icons.description, color: AppTheme.accent, size: 14),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            content,
                            style: const TextStyle(fontSize: 12, color: AppTheme.textPrimary),
                          ),
                          if (place.isNotEmpty)
                            Text(
                              '📍 $place',
                              style: const TextStyle(fontSize: 10, color: AppTheme.textSecondary),
                            ),
                        ],
                      ),
                    ),
                  ],
                );
              },
            ),
        ],
      ),
    );
  }
}
