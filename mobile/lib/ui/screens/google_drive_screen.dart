import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../services/google_drive_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';

class GoogleDriveScreen extends StatefulWidget {
  const GoogleDriveScreen({super.key});
  @override
  State<GoogleDriveScreen> createState() => _GoogleDriveScreenState();
}

class _GoogleDriveScreenState extends State<GoogleDriveScreen> {
  final _drive = GoogleDriveService.instance;
  bool _busy = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    _drive.addListener(_changed);
    _drive.restoreConnection();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _drive.removeListener(_changed);
    super.dispose();
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
          () => _error = e is DriveFailure
              ? e.message
              : e is PlatformException
              ? e.message
              : 'Google Drive is unavailable. Try again.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _results({bool reset = false}) async {
    try {
      await _drive.loadIndexResults(reset: reset);
    } catch (error) {
      if (mounted) {
        setState(
          () => _error = error is DriveFailure
              ? error.message
              : 'File results are temporarily unavailable.',
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Google Drive & file memory')),
    body: WorkspaceBody(
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const PageIntro(
            title: 'Search and read your Drive',
            description:
                'Ask about existing Drive files or attach a file in chat. Say “save to Google Drive” to save a new attachment.',
          ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _drive.connected
                        ? _drive.email
                        : GoogleDriveService.defaultAccount,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 12),
                  if (_drive.connected)
                    const Text(
                      'Connected',
                      style: TextStyle(color: AppTheme.green),
                    ),
                  const Text(
                    'Allow read access to search existing Drive files. Write access is limited to files shared with Jarvis or created by Jarvis.',
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Direct reading supports PDFs, images, videos and PDF exports of Google Docs, Sheets and Slides up to 20 MB. Uploads support up to 250 MB.',
                    style: TextStyle(color: AppTheme.textSecondary),
                  ),
                  const SizedBox(height: 16),
                  if ((_busy && !_drive.indexing) || _drive.restoring)
                    const LinearProgressIndicator()
                  else
                    Wrap(
                      spacing: 12,
                      runSpacing: 12,
                      children: [
                        if (!_drive.connected)
                          FilledButton.icon(
                            onPressed: () => _run(_drive.connect),
                            icon: const Icon(Icons.link),
                            label: Text(
                              _drive.needsReconnect
                                  ? 'Reconnect Google account'
                                  : 'Connect Google account',
                            ),
                          ),
                        if (_drive.connected)
                          OutlinedButton(
                            onPressed: () => _run(_drive.syncMemories),
                            child: const Text('Refresh files'),
                          ),
                        if (_drive.connected)
                          OutlinedButton.icon(
                            onPressed: _drive.indexing
                                ? _drive.stopIndexing
                                : () => _run(_drive.indexAllDrive),
                            icon: Icon(
                              _drive.indexing ? Icons.pause : Icons.search,
                            ),
                            label: Text(
                              _drive.indexing
                                  ? 'Pause indexing'
                                  : 'Index Drive contents',
                            ),
                          ),
                        if (_drive.connected)
                          TextButton(
                            onPressed: () async {
                              final approved = await showDialog<bool>(
                                context: context,
                                builder: (ctx) => AlertDialog(
                                  title: const Text('Disconnect Google Drive?'),
                                  content: const Text(
                                    'File memory and saved originals stay available. Jarvis loses Drive access on this phone. You can also revoke the grant in your Google account settings.',
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
                              if (approved == true) {
                                await _run(_drive.disconnect);
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
          const SizedBox(height: 24),
          const Text(
            'Index Office documents, spreadsheets, presentations, archives, media, text, Google documents and Forms. Shortcuts resolve to their targets. Binary files include metadata and readable strings. Every file gets a result, including content that needs access or a password. Keep Jarvis open during submission; processing continues afterward.',
          ),
          if (_drive.indexProgress.isNotEmpty) Text(_drive.indexProgress),
          if (_drive.connected)
            TextButton(
              onPressed: () => _results(reset: true),
              child: const Text('View file indexing results'),
            ),
          for (final result in _drive.indexResults)
            ListTile(
              title: Text(result['name'].toString()),
              subtitle: Text(
                '${result['status']} · ${result['coverage']}\n${(result['issues'] as Map? ?? {}).keys.join('; ')}${result['error'] ?? ''}',
              ),
            ),
          if (_drive.indexResultsCursor != null)
            TextButton(
              onPressed: _results,
              child: const Text('Load more results'),
            ),
          Text(
            'File memory · ${_drive.memories.length}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 12),
          if (_drive.memories.isEmpty)
            const Text(
              'Attach a file in chat and describe what you want Jarvis to remember.',
            )
          else
            Card(
              child: Column(
                children: [
                  for (final file in _drive.memories.reversed)
                    ListTile(
                      leading: Icon(
                        '${file['mimeType']}'.startsWith('video/')
                            ? Icons.video_file_outlined
                            : '${file['mimeType']}'.startsWith('image/')
                            ? Icons.image_outlined
                            : Icons.picture_as_pdf_outlined,
                        color: AppTheme.primaryLight,
                      ),
                      title: Text(file['name'].toString()),
                      subtitle: Text(
                        '${GoogleDriveService.sizeLabel(file['size'] as num)} · ${file['caption']}',
                      ),
                      trailing: const Icon(Icons.open_in_new, size: 18),
                      onTap: () => _run(() => _drive.open(file)),
                    ),
                ],
              ),
            ),
        ],
      ),
    ),
  );
}
