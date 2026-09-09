import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import '../../models/recording_session.dart';
import '../../services/session_storage_service.dart';
import '../theme.dart';

/// Screen displaying all recorded data collection sessions stored on device.
/// Allows sharing, previewing, and managing CSV/JSON files.
class SessionsScreen extends StatefulWidget {
  const SessionsScreen({super.key});

  @override
  State<SessionsScreen> createState() => _SessionsScreenState();
}

class _SessionsScreenState extends State<SessionsScreen> {
  List<RecordingSession> _sessions = [];
  bool _isLoading = true;
  String _storagePath = '';

  @override
  void initState() {
    super.initState();
    _loadSessions();
  }

  Future<void> _loadSessions() async {
    setState(() => _isLoading = true);
    final dir = await SessionStorageService.getStorageDir();
    final sessions = await SessionStorageService.listSessions();
    if (mounted) {
      setState(() {
        _storagePath = dir.path;
        _sessions = sessions;
        _isLoading = false;
      });
    }
  }

  Future<void> _deleteSession(RecordingSession session) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.surfaceBright,
        title: const Text('Delete Recording?'),
        content: Text(
          'Are you sure you want to delete ${session.id} (${session.formattedSize})?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('CANCEL'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('DELETE'),
          ),
        ],
      ),
    );

    if (confirm == true) {
      await SessionStorageService.deleteSession(session);
      await _loadSessions();
    }
  }

  Future<void> _previewCsv(RecordingSession session) async {
    final file = File(session.csvFilePath);
    if (!await file.exists()) return;

    final lines = await file
        .openRead()
        .transform(const SystemEncoding().decoder)
        .transform(const LineSplitter())
        .take(15)
        .toList();

    if (!mounted) return;

    showModalBottomSheet(
      context: context,
      backgroundColor: AppTheme.surfaceBright,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Container(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'CSV PREVIEW (First 15 Rows)',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    color: AppTheme.cyan,
                    fontSize: 14,
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.pop(ctx),
                ),
              ],
            ),
            Text(
              session.csvFilePath,
              style: const TextStyle(
                color: AppTheme.textSecondary,
                fontSize: 11,
                fontFamily: 'monospace',
              ),
            ),
            const Divider(color: AppTheme.border),
            Expanded(
              child: SingleChildScrollView(
                scrollDirection: Axis.vertical,
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: SelectableText(
                    lines.join('\n'),
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 10,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _previewJson(RecordingSession session) async {
    final file = File(session.jsonFilePath);
    if (!await file.exists()) return;

    String formattedContent;
    try {
      final raw = await file.readAsString();
      final obj = jsonDecode(raw);
      formattedContent = const JsonEncoder.withIndent('  ').convert(obj);
    } catch (_) {
      formattedContent = await file.readAsString();
    }

    if (!mounted) return;

    showModalBottomSheet(
      context: context,
      backgroundColor: AppTheme.surfaceBright,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Container(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Row(
                  children: [
                    Icon(Icons.data_object, color: AppTheme.green, size: 18),
                    SizedBox(width: 8),
                    Text(
                      'LOW TELEMETRY (Cloud JSON)',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        color: AppTheme.green,
                        fontSize: 14,
                      ),
                    ),
                  ],
                ),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.pop(ctx),
                ),
              ],
            ),
            Text(
              session.jsonFilePath,
              style: const TextStyle(
                color: AppTheme.textSecondary,
                fontSize: 11,
                fontFamily: 'monospace',
              ),
            ),
            const Divider(color: AppTheme.border),
            Expanded(
              child: SingleChildScrollView(
                scrollDirection: Axis.vertical,
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: SelectableText(
                    formattedContent,
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 11,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('RECORDED SESSIONS'),
        actions: [
          IconButton(
            tooltip: 'Refresh list',
            icon: const Icon(Icons.refresh),
            onPressed: _loadSessions,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            // Directory Path Banner
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              color: AppTheme.surface,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'PHONE STORAGE FOLDER (Open in File Manager)',
                    style: TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.0,
                    ),
                  ),
                  const SizedBox(height: 2),
                  SelectableText(
                    _storagePath.isEmpty ? 'Locating...' : _storagePath,
                    style: const TextStyle(
                      color: AppTheme.cyan,
                      fontSize: 12,
                      fontFamily: 'monospace',
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1, color: AppTheme.border),

            // Sessions List
            Expanded(
              child: _isLoading
                  ? const Center(
                      child: CircularProgressIndicator(color: AppTheme.cyan),
                    )
                  : _sessions.isEmpty
                      ? _buildEmptyState()
                      : ListView.separated(
                          padding: const EdgeInsets.all(12),
                          itemCount: _sessions.length,
                          separatorBuilder: (_, _) =>
                              const SizedBox(height: 10),
                          itemBuilder: (context, index) {
                            final session = _sessions[index];
                            return _buildSessionCard(session);
                          },
                        ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: const [
          Icon(Icons.folder_open, size: 64, color: AppTheme.textSecondary),
          SizedBox(height: 12),
          Text(
            'No Recorded Telemetry Yet',
            style: TextStyle(
              color: AppTheme.textPrimary,
              fontSize: 16,
              fontWeight: FontWeight.bold,
            ),
          ),
          SizedBox(height: 6),
          Text(
            'Tap "START DATA COLLECTION" on the dashboard\nto record real IMU and GPS runs.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppTheme.textSecondary,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSessionCard(RecordingSession session) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Row 1: Label Badge, Duration, Size
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: AppTheme.cyan.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AppTheme.cyan),
                ),
                child: Text(
                  session.label,
                  style: const TextStyle(
                    color: AppTheme.cyan,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              Row(
                children: [
                  Text(
                    '${session.formattedDuration} • ${session.sampleCount} pts',
                    style: const TextStyle(
                      color: AppTheme.textPrimary,
                      fontWeight: FontWeight.bold,
                      fontSize: 12,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    session.formattedSize,
                    style: const TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ],
          ),

          const SizedBox(height: 8),

          // Row 2: Mount & Road Condition
          Text(
            'Mount: ${session.mountPosition}  |  Road: ${session.roadCondition}',
            style: const TextStyle(
              color: AppTheme.textSecondary,
              fontSize: 11,
            ),
          ),

          const SizedBox(height: 4),

          // Row 3: Recorded Date
          Text(
            'Recorded: ${session.startTime.toLocal().toString().split('.').first}',
            style: const TextStyle(
              color: AppTheme.textSecondary,
              fontSize: 11,
              fontFamily: 'monospace',
            ),
          ),

          const SizedBox(height: 10),

          // Action Buttons: CSV High, JSON Low, Share, Delete
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton.icon(
                icon: const Icon(Icons.table_chart_outlined, size: 14),
                label: const Text('CSV (HIGH)'),
                style: TextButton.styleFrom(
                  foregroundColor: AppTheme.cyan,
                  visualDensity: VisualDensity.compact,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                ),
                onPressed: () => _previewCsv(session),
              ),
              const SizedBox(width: 4),
              TextButton.icon(
                icon: const Icon(Icons.data_object_rounded, size: 14),
                label: const Text('JSON (LOW)'),
                style: TextButton.styleFrom(
                  foregroundColor: AppTheme.green,
                  visualDensity: VisualDensity.compact,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                ),
                onPressed: () => _previewJson(session),
              ),
              const SizedBox(width: 4),
              IconButton(
                tooltip: 'Share recording',
                icon: const Icon(Icons.share, color: AppTheme.amber, size: 18),
                visualDensity: VisualDensity.compact,
                onPressed: () => SessionStorageService.shareSession(session),
              ),
              IconButton(
                tooltip: 'Delete recording',
                icon: const Icon(Icons.delete_outline,
                    color: AppTheme.red, size: 18),
                visualDensity: VisualDensity.compact,
                onPressed: () => _deleteSession(session),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
