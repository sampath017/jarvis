import 'package:flutter/material.dart';
import '../../services/local_db_service.dart';
import '../../services/sensor_service.dart';
import '../../services/sync_service.dart';
import '../widgets/notes_workspace.dart';

class NotesScreen extends StatefulWidget {
  final SensorService sensorService;
  const NotesScreen({super.key, required this.sensorService});
  @override
  State<NotesScreen> createState() => _NotesScreenState();
}

class _NotesScreenState extends State<NotesScreen> {
  final _db = LocalDbService();
  final _sync = SyncService();
  List<Map<String, dynamic>> _notes = [];
  List<Map<String, dynamic>> _trash = [];
  bool _loading = true;
  @override
  void initState() {
    super.initState();
    _db.addListener(_load);
    _load();
    _refresh();
  }

  @override
  void dispose() {
    _db.removeListener(_load);
    super.dispose();
  }

  Future<void> _load() async {
    final notes = await _db.getNotes();
    final trash = await _db.getNotes(deleted: true);
    if (mounted) {
      setState(() {
        _notes = notes;
        _trash = trash;
        _loading = false;
      });
    }
  }

  Future<void> _refresh() async {
    try {
      await _sync.syncNow();
    } catch (_) {
      // Local edits stay pending and are retried by the sync service.
    }
    await _load();
  }

  Future<void> _save(Map<String, dynamic> note) async {
    await _db.saveNote(note);
    await _load();
    _refresh();
  }

  Future<void> _delete(String id) async {
    await _db.deleteNote(id);
    await _load();
    _refresh();
  }

  Future<void> _restore(String id) async {
    await _db.restoreNote(id);
    await _load();
    _refresh();
  }

  @override
  Widget build(BuildContext context) => NotesWorkspace(
    notes: _notes,
    trash: _trash,
    loading: _loading,
    onRefresh: _refresh,
    onSave: _save,
    onDelete: _delete,
    onRestore: _restore,
  );
}
