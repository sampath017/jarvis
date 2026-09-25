import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/local_db_service.dart';
import '../../services/sensor_service.dart';
import '../../services/sync_service.dart';
import '../theme.dart';
import '../widgets/workspace_widgets.dart';

/// Dedicated Notes Screen:
/// Displays all context notes, memos, and logs stored locally in SQLite,
/// synchronized seamlessly with Google Cloud Firestore.
class NotesScreen extends StatefulWidget {
  final SensorService sensorService;

  const NotesScreen({super.key, required this.sensorService});

  @override
  State<NotesScreen> createState() => _NotesScreenState();
}

class _NotesScreenState extends State<NotesScreen> {
  final ApiService _apiService = ApiService();
  final LocalDbService _localDb = LocalDbService();
  final SyncService _syncService = SyncService();

  List<Map<String, dynamic>> _notes = [];
  List<Map<String, dynamic>> _trashedNotes = [];
  bool _showTrash = false;
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _apiService.addListener(_onApiServiceUpdate);
    _localDb.addListener(_onLocalDbUpdate);
    _initAndLoad();
  }

  @override
  void dispose() {
    _apiService.removeListener(_onApiServiceUpdate);
    _localDb.removeListener(_onLocalDbUpdate);
    super.dispose();
  }

  void _onApiServiceUpdate() {
    if (mounted) setState(() {});
  }

  void _onLocalDbUpdate() {
    _refreshFromLocalDb();
  }

  Future<void> _initAndLoad() async {
    await _refreshFromLocalDb();
    _syncWithCloud();
  }

  Future<void> _refreshFromLocalDb() async {
    final list = await _localDb.getNotes();
    final trashed = await _localDb.getNotes(deleted: true);
    if (mounted) {
      setState(() {
        _notes = list;
        _trashedNotes = trashed;
      });
    }
  }

  Future<void> _syncWithCloud() async {
    try {
      await _syncService.syncNow();
      await _refreshFromLocalDb();
    } catch (_) {}
    if (mounted && _isLoading) setState(() => _isLoading = false);
  }

  void _showAddNoteDialog() {
    final contentCtrl = TextEditingController();
    final placeCtrl = TextEditingController();

    // Autofill place if we have current GPS context
    if (widget.sensorService.hasGpsFix) {
      placeCtrl.text =
          'Lat ${widget.sensorService.lat.toStringAsFixed(3)}, Lon ${widget.sensorService.lon.toStringAsFixed(3)}';
    }

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.surfaceBright,
        title: const Row(
          children: [
            Icon(Icons.note_add, color: AppTheme.accent, size: 22),
            SizedBox(width: 8),
            Text(
              'New note',
              style: TextStyle(
                color: AppTheme.textPrimary,
                fontSize: 14,
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: contentCtrl,
              maxLines: 3,
              style: const TextStyle(color: AppTheme.textPrimary, fontSize: 13),
              decoration: const InputDecoration(
                labelText: 'Note Content',
                labelStyle: TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 12,
                ),
                hintText: 'e.g. Odometer reading at start: 4,285 km',
                hintStyle: TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 11,
                ),
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: placeCtrl,
              style: const TextStyle(color: AppTheme.textPrimary, fontSize: 13),
              decoration: const InputDecoration(
                labelText: 'Context Place / Tag',
                labelStyle: TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 12,
                ),
                hintText: 'e.g. Home Garage / RE Showroom',
                hintStyle: TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 11,
                ),
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.place, color: AppTheme.accent, size: 18),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text(
              'Cancel',
              style: TextStyle(color: AppTheme.textSecondary),
            ),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.primary,
              foregroundColor: Colors.white,
            ),
            onPressed: () async {
              if (contentCtrl.text.trim().isEmpty) return;
              Navigator.pop(ctx);
              final now = DateTime.now().toUtc().toIso8601String();
              final newNote = {
                'id': 'note-${DateTime.now().millisecondsSinceEpoch}',
                'title': 'Context Note',
                'content': contentCtrl.text.trim(),
                'place': placeCtrl.text.trim().isEmpty
                    ? null
                    : placeCtrl.text.trim(),
                'created_at': now,
                'updated_at': now,
              };
              await _localDb.saveNote(newNote);
              _refreshFromLocalDb();
              _syncService.syncNow();
            },
            child: const Text('Save note'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final notes = _showTrash ? _trashedNotes : _notes;

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: Text(_showTrash ? 'Note Trash' : 'Notes'),
        actions: [
          TextButton.icon(
            icon: Icon(_showTrash ? Icons.arrow_back : Icons.delete_outline),
            label: Text(_showTrash ? 'Back' : 'Trash'),
            onPressed: () => setState(() => _showTrash = !_showTrash),
          ),
        ],
      ),
      floatingActionButton: _showTrash
          ? null
          : FloatingActionButton.extended(
              backgroundColor: AppTheme.primary,
              foregroundColor: Colors.white,
              icon: const Icon(Icons.add),
              label: const Text(
                'New note',
                style: TextStyle(fontWeight: FontWeight.w600),
              ),
              onPressed: _showAddNoteDialog,
            ),
      body: (_isLoading && notes.isEmpty)
          ? const Center(
              child: CircularProgressIndicator(color: AppTheme.accent),
            )
          : WorkspaceBody(
              child: RefreshIndicator(
                onRefresh: _syncWithCloud,
                backgroundColor: AppTheme.surfaceBright,
                color: AppTheme.accent,
                child: ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(24, 16, 24, 104),
                  children: [
                    if (!_showTrash)
                      PageIntro(
                        title: 'Your notes',
                        description:
                            'Ideas, details, and things worth remembering.',
                        trailing: Text(
                          '${notes.length} saved',
                          style: const TextStyle(
                            color: AppTheme.textSecondary,
                            fontSize: 12,
                          ),
                        ),
                      ),
                    if (notes.isEmpty)
                      _showTrash
                          ? const Center(
                              child: Padding(
                                padding: EdgeInsets.all(32),
                                child: Text(
                                  'Trash is empty',
                                  style: TextStyle(
                                    color: AppTheme.textSecondary,
                                  ),
                                ),
                              ),
                            )
                          : _buildEmptyState()
                    else
                      for (final n in notes) ...[
                        _buildNoteTile(n),
                        const SizedBox(height: 10),
                      ],
                  ],
                ),
              ),
            ),
    );
  }

  Widget _buildNoteTile(Map<String, dynamic> n) {
    final id = n['id']?.toString() ?? '';
    final content = n['content'] ?? '';
    final place = n['place'] ?? '';
    final createdAt = n['created_at']?.toString().split('T')[0] ?? '';

    return Container(
      padding: const EdgeInsets.fromLTRB(16, 14, 8, 14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 1),
            child: Icon(
              _showTrash
                  ? Icons.inventory_2_outlined
                  : Icons.sticky_note_2_outlined,
              color: _showTrash
                  ? AppTheme.textSecondary
                  : AppTheme.primaryLight,
              size: 22,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  content,
                  style: const TextStyle(
                    fontSize: 15,
                    height: 1.55,
                    fontWeight: FontWeight.w500,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    if (place.isNotEmpty) ...[
                      const Icon(
                        Icons.place_outlined,
                        color: AppTheme.textSecondary,
                        size: 12,
                      ),
                      const SizedBox(width: 3),
                      Flexible(
                        child: Text(
                          place,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppTheme.textSecondary,
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                    ],
                    if (createdAt.isNotEmpty) ...[
                      const Icon(
                        Icons.calendar_today,
                        color: AppTheme.textSecondary,
                        size: 11,
                      ),
                      const SizedBox(width: 3),
                      Text(
                        createdAt,
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppTheme.textSecondary,
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
          IconButton(
            icon: Icon(
              _showTrash ? Icons.restore : Icons.move_to_inbox_outlined,
              color: _showTrash ? AppTheme.primary : AppTheme.textSecondary,
              size: 20,
            ),
            tooltip: _showTrash ? 'Restore Note' : 'Move to Trash',
            onPressed: () async {
              if (_showTrash) {
                await _localDb.restoreNote(id);
              } else {
                await _localDb.deleteNote(id);
              }
              _refreshFromLocalDb();
              _syncService.syncNow();
            },
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() => const WorkspaceEmptyState(
    icon: Icons.note_alt_outlined,
    title: 'No notes yet',
    description:
        'Create your first note below, or ask Jarvis to remember something in chat.',
  );
}
