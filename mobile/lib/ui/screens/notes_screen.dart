import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/local_db_service.dart';
import '../../services/sensor_service.dart';
import '../../services/sync_service.dart';
import '../theme.dart';

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
    if (mounted) {
      setState(() {
        _notes = list;
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
      placeCtrl.text = 'Lat ${widget.sensorService.lat.toStringAsFixed(3)}, Lon ${widget.sensorService.lon.toStringAsFixed(3)}';
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
              'NEW CONTEXT NOTE',
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
                labelStyle: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                hintText: 'e.g. Odometer reading at start: 4,285 km',
                hintStyle: TextStyle(color: AppTheme.textSecondary, fontSize: 11),
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: placeCtrl,
              style: const TextStyle(color: AppTheme.textPrimary, fontSize: 13),
              decoration: const InputDecoration(
                labelText: 'Context Place / Tag',
                labelStyle: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                hintText: 'e.g. Home Garage / RE Showroom',
                hintStyle: TextStyle(color: AppTheme.textSecondary, fontSize: 11),
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.place, color: AppTheme.accent, size: 18),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('CANCEL', style: TextStyle(color: AppTheme.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.accent, foregroundColor: Colors.black),
            onPressed: () async {
              if (contentCtrl.text.trim().isEmpty) return;
              Navigator.pop(ctx);
              final now = DateTime.now().toUtc().toIso8601String();
              final newNote = {
                'id': 'note-${DateTime.now().millisecondsSinceEpoch}',
                'title': 'Context Note',
                'content': contentCtrl.text.trim(),
                'place': placeCtrl.text.trim().isEmpty ? null : placeCtrl.text.trim(),
                'created_at': now,
                'updated_at': now,
              };
              await _localDb.saveNote(newNote);
              _refreshFromLocalDb();
              _syncService.syncNow();
            },
            child: const Text('SAVE NOTE'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final notes = _notes;

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        title: const Text(
          'Notes',
          style: TextStyle(
            fontWeight: FontWeight.bold,
            letterSpacing: 0.5,
            fontSize: 16,
          ),
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: AppTheme.accent,
        foregroundColor: Colors.black,
        icon: const Icon(Icons.add),
        label: const Text('NEW NOTE', style: TextStyle(fontWeight: FontWeight.bold)),
        onPressed: _showAddNoteDialog,
      ),
      body: (_isLoading && notes.isEmpty)
          ? const Center(child: CircularProgressIndicator(color: AppTheme.accent))
          : RefreshIndicator(
              onRefresh: _syncWithCloud,
              backgroundColor: AppTheme.surfaceBright,
              color: AppTheme.accent,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
                children: [
                  if (notes.isEmpty)
                    _buildEmptyState()
                  else
                    for (final n in notes) ...[
                      _buildNoteTile(n),
                      const SizedBox(height: 10),
                    ],
                ],
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
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: AppTheme.accent.withAlpha(30),
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.sticky_note_2, color: AppTheme.accent, size: 18),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  content,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    if (place.isNotEmpty) ...[
                      const Icon(Icons.place, color: AppTheme.accent, size: 12),
                      const SizedBox(width: 3),
                      Text(place, style: const TextStyle(fontSize: 10.5, color: AppTheme.accent)),
                      const SizedBox(width: 10),
                    ],
                    if (createdAt.isNotEmpty) ...[
                      const Icon(Icons.calendar_today, color: AppTheme.textSecondary, size: 11),
                      const SizedBox(width: 3),
                      Text(createdAt, style: const TextStyle(fontSize: 10, color: AppTheme.textSecondary)),
                    ],
                  ],
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline, color: AppTheme.red, size: 18),
            onPressed: () async {
              await _localDb.deleteNote(id);
              await _apiService.deleteNote(id);
              _refreshFromLocalDb();
              _syncService.syncNow();
            },
          ),
        ],
      ),
    );
  }


  Widget _buildEmptyState() {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 40),
      alignment: Alignment.center,
      child: Column(
        children: [
          Icon(Icons.notes, color: AppTheme.textSecondary.withAlpha(100), size: 48),
          const SizedBox(height: 12),
          const Text(
            'No Notes Logged',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: AppTheme.textPrimary),
          ),
          const SizedBox(height: 4),
          const Text(
            'Tap "+ NEW NOTE" or chat with Jarvis to\nlog trip memos, maintenance notes, and fuel readings.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 11, color: AppTheme.textSecondary),
          ),
        ],
      ),
    );
  }
}
