import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../models/recording_session.dart';
import '../../services/session_storage_service.dart';
import '../../services/session_preferences.dart';
import '../../services/recording_backup_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';

class SessionsScreen extends StatefulWidget {
  const SessionsScreen({super.key});
  @override
  State<SessionsScreen> createState() => _SessionsScreenState();
}

class _SessionsScreenState extends State<SessionsScreen> {
  final _backup = RecordingBackupService();
  final _store = SessionPreferences();
  Map<String, Map<String, Object?>> _prefs = {};
  List<RecordingSession> _sessions = [];
  Set<String> _cloud = {};
  bool _loading = true, _archived = false, _oldest = false;
  String _query = '';
  String? _error, _busy;
  @override
  void initState() {
    super.initState();
    _load();
  }

  String _key(RecordingSession s) => 'recording:${s.id}';
  String _name(RecordingSession s) =>
      _prefs[_key(s)]?['name'] as String? ??
      '${s.label.replaceAll('_', ' ')} recording';
  bool _hidden(RecordingSession s) => _prefs[_key(s)]?['archived'] == 1;
  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final local = await SessionStorageService.listSessions();
      final prefs = await _store.load();
      List<RecordingSession> remote = [];
      String? error;
      try {
        remote = await _backup.list();
      } catch (_) {
        error = 'Cloud library unavailable. Showing downloaded recordings.';
      }
      if (!mounted) return;
      final merged = {
        for (final s in remote) s.id: s,
        for (final s in local) s.id: s,
      };
      setState(() {
        _sessions = merged.values.toList();
        _prefs = prefs;
        _cloud = remote.map((s) => s.id).toSet();
        _error = error;
        _loading = false;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Could not load recordings. Pull down to retry.';
        });
      }
    }
  }

  Future<void> _action(RecordingSession session, String action) async {
    if (_busy != null) return;
    if (action == 'rename') {
      var name = _name(session);
      final result = await showDialog<String>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Name this recording'),
          content: TextFormField(
            initialValue: name,
            maxLength: 60,
            autofocus: true,
            onChanged: (value) => name = value,
            decoration: const InputDecoration(labelText: 'Recording name'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, name.trim()),
              child: const Text('Save'),
            ),
          ],
        ),
      );
      if (result == null || !mounted) return;
      setState(() => _busy = session.id);
      try {
        await _store.save(
          _key(session),
          result.isEmpty ? null : result,
          _hidden(session),
        );
        await _load();
      } catch (_) {
        _notice('Could not save to Firebase. Please retry.');
      } finally {
        if (mounted) setState(() => _busy = null);
      }
      return;
    }
    setState(() => _busy = session.id);
    try {
      if (action == 'archive') {
        await _store.save(
          _key(session),
          _prefs[_key(session)]?['name'] as String?,
          !_hidden(session),
        );
      } else if (action == 'backup') {
        await _backup.backup(session);
      } else {
        var local = session;
        if (local.csvFilePath.isEmpty ||
            local.jsonFilePath.isEmpty ||
            !await File(local.csvFilePath).exists() ||
            !await File(local.jsonFilePath).exists()) {
          local = await _backup.restore(session);
        }
        if (action == 'share') await SessionStorageService.shareSession(local);
        if (action == 'preview') {
          final lines = await File(local.csvFilePath)
              .openRead()
              .transform(utf8.decoder)
              .transform(const LineSplitter())
              .take(16)
              .toList();
          if (mounted) {
            await showModalBottomSheet<void>(
              context: context,
              isScrollControlled: true,
              showDragHandle: true,
              builder: (_) => SafeArea(
                child: SizedBox(
                  height: MediaQuery.sizeOf(context).height * .65,
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Recording preview',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const Text(
                          'First 15 samples. Share to export the full files.',
                        ),
                        const SizedBox(height: 16),
                        Expanded(
                          child: SingleChildScrollView(
                            child: SingleChildScrollView(
                              scrollDirection: Axis.horizontal,
                              child: SelectableText(
                                lines.join('\n'),
                                style: const TextStyle(
                                  fontFamily: 'monospace',
                                  fontSize: 12,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          }
        }
      }
      if (mounted) await _load();
    } catch (_) {
      _notice(
        'Could not complete this action. Please check your connection and retry.',
      );
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  void _notice(String text) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final visible =
        _sessions
            .where(
              (s) =>
                  _hidden(s) == _archived &&
                  '${_name(s)} ${DateFormat.yMMMd().format(s.startTime.toLocal())}'
                      .toLowerCase()
                      .contains(_query.toLowerCase()),
            )
            .toList()
          ..sort(
            (a, b) => _oldest
                ? a.startTime.compareTo(b.startTime)
                : b.startTime.compareTo(a.startTime),
          );
    return Scaffold(
      appBar: AppBar(
        title: const Text('Recordings'),
        actions: [
          IconButton(
            tooltip: 'Refresh recordings',
            onPressed: _busy == null && !_loading ? _load : null,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: WorkspaceBody(
        child: RefreshIndicator(
          onRefresh: () async {
            if (_busy == null) await _load();
          },
          child: ListView(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 32),
            physics: const AlwaysScrollableScrollPhysics(),
            children: [
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppTheme.radius),
                  color: AppTheme.surface,
                  border: Border.all(color: AppTheme.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(
                      Icons.folder_copy_outlined,
                      color: AppTheme.accent,
                      size: 30,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '${_sessions.length} saved recordings',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '${_cloud.length} backed up · ${_sessions.where((s) => !_cloud.contains(s.id)).length} awaiting backup',
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Backed-up files, names and archives survive a reinstall. Pending files retry while Jarvis is open. Files up to 128 MB are supported.',
                      style: TextStyle(color: AppTheme.textSecondary),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                decoration: const InputDecoration(
                  hintText: 'Search name or date',
                  prefixIcon: Icon(Icons.search),
                ),
                onChanged: (value) => setState(() => _query = value),
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                children: [
                  FilterChip(
                    label: const Text('Archive'),
                    selected: _archived,
                    onSelected: (v) => setState(() => _archived = v),
                  ),
                  ActionChip(
                    label: Text(_oldest ? 'Oldest first' : 'Newest first'),
                    avatar: const Icon(Icons.sort, size: 18),
                    onPressed: () => setState(() => _oldest = !_oldest),
                  ),
                ],
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Text(
                    _error!,
                    style: const TextStyle(color: AppTheme.amber),
                  ),
                ),
              if (_loading) const LinearProgressIndicator(),
              if (!_loading && visible.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(32),
                  child: Text(
                    'No recordings here. Try another search or check the archive.',
                    textAlign: TextAlign.center,
                  ),
                ),
              for (final s in visible)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  _name(s),
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                    fontSize: 17,
                                  ),
                                ),
                              ),
                              PopupMenuButton<String>(
                                enabled: _busy == null,
                                tooltip: 'Manage recording',
                                onSelected: (value) => _action(s, value),
                                itemBuilder: (_) => [
                                  const PopupMenuItem(
                                    value: 'rename',
                                    child: Text('Rename'),
                                  ),
                                  PopupMenuItem(
                                    value: 'archive',
                                    child: Text(
                                      _hidden(s)
                                          ? 'Restore from archive'
                                          : 'Archive',
                                    ),
                                  ),
                                  const PopupMenuItem(
                                    value: 'preview',
                                    child: Text('Preview data'),
                                  ),
                                  const PopupMenuItem(
                                    value: 'share',
                                    child: Text('Share files'),
                                  ),
                                ],
                              ),
                            ],
                          ),
                          Text(
                            DateFormat(
                              'EEE, d MMM y · h:mm a',
                            ).format(s.startTime.toLocal()),
                            style: const TextStyle(
                              color: AppTheme.textSecondary,
                            ),
                          ),
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 16,
                            runSpacing: 8,
                            children: [
                              Text(s.formattedDuration),
                              Text(s.formattedSize),
                              Text('${s.sampleCount} samples'),
                            ],
                          ),
                          const Divider(height: 24),
                          if (_busy == s.id)
                            const LinearProgressIndicator()
                          else
                            Row(
                              children: [
                                Icon(
                                  _cloud.contains(s.id)
                                      ? Icons.cloud_done_outlined
                                      : Icons.cloud_upload_outlined,
                                  size: 18,
                                  color: _cloud.contains(s.id)
                                      ? AppTheme.green
                                      : AppTheme.amber,
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    _cloud.contains(s.id)
                                        ? 'Backed up'
                                        : s.csvSizeBytes > 128 * 1024 * 1024
                                        ? 'Too large for backup · Share to export'
                                        : 'On this phone only',
                                  ),
                                ),
                                if (!_cloud.contains(s.id) &&
                                    s.csvSizeBytes <= 128 * 1024 * 1024)
                                  TextButton(
                                    onPressed: _busy == null
                                        ? () => _action(s, 'backup')
                                        : null,
                                    child: const Text('Back up'),
                                  )
                                else if (s.csvFilePath.isEmpty)
                                  TextButton(
                                    onPressed: _busy == null
                                        ? () => _action(s, 'download')
                                        : null,
                                    child: const Text('Download'),
                                  ),
                              ],
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
              const SizedBox(height: 32),
            ],
          ),
        ),
      ),
    );
  }
}
