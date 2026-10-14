import 'package:flutter/material.dart';
import '../theme.dart';
import 'workspace_widgets.dart';

String noteTitle(Map<String, dynamic> note) {
  final title = (note['title'] ?? '').toString().trim();
  if (title.isNotEmpty && title != 'Context Note' && title != 'Note') {
    return title;
  }
  final firstLine = (note['content'] ?? '').toString().trim().split('\n').first;
  return firstLine.isEmpty ? 'Untitled note' : firstLine;
}

/// Storage-independent interactions, shared by the app and widget tests.
class NotesWorkspace extends StatefulWidget {
  const NotesWorkspace({
    super.key,
    required this.notes,
    required this.trash,
    required this.onSave,
    required this.onDelete,
    required this.onRestore,
    required this.onRefresh,
    this.loading = false,
  });
  final List<Map<String, dynamic>> notes;
  final List<Map<String, dynamic>> trash;
  final Future<void> Function(Map<String, dynamic>) onSave;
  final Future<void> Function(String) onDelete;
  final Future<void> Function(String) onRestore;
  final Future<void> Function() onRefresh;
  final bool loading;
  @override
  State<NotesWorkspace> createState() => _NotesWorkspaceState();
}

class _NotesWorkspaceState extends State<NotesWorkspace> {
  bool _showTrash = false;
  String _query = '';
  final _busy = <String>{};

  Future<bool> _delete(Map<String, dynamic> note) async {
    final id = note['id'].toString();
    if (_busy.contains(id)) return false;
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this note?'),
        content: Text(
          '“${noteTitle(note)}” will move to Trash. You can restore it later.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete note'),
          ),
        ],
      ),
    );
    if (approved != true || !mounted) return false;
    setState(() => _busy.add(id));
    try {
      await widget.onDelete(id);
      return true;
    } catch (_) {
      _error('Could not delete this note. Please try again.');
      return false;
    } finally {
      if (mounted) setState(() => _busy.remove(id));
    }
  }

  void _error(String message) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _restore(Map<String, dynamic> note) async {
    final id = note['id'].toString();
    if (_busy.contains(id)) return;
    setState(() => _busy.add(id));
    try {
      await widget.onRestore(id);
    } catch (_) {
      _error('Could not restore this note. Please try again.');
    } finally {
      if (mounted) setState(() => _busy.remove(id));
    }
  }

  Future<void> _open([Map<String, dynamic>? note]) => showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _NoteEditor(
      note: note,
      readOnly: _showTrash,
      onSave: widget.onSave,
      onDelete: note == null ? null : () => _delete(note),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final source = _showTrash ? widget.trash : widget.notes;
    final notes = source
        .where(
          (note) => '${note['title']} ${note['content']} ${note['place']}'
              .toLowerCase()
              .contains(_query.toLowerCase()),
        )
        .toList();
    return Scaffold(
      appBar: AppBar(
        title: Text(_showTrash ? 'Note Trash' : 'Notes'),
        actions: [
          TextButton.icon(
            onPressed: () => setState(() => _showTrash = !_showTrash),
            icon: Icon(_showTrash ? Icons.notes : Icons.delete_outline),
            label: Text(_showTrash ? 'Notes' : 'Trash'),
          ),
        ],
      ),
      floatingActionButton: _showTrash
          ? null
          : FloatingActionButton.extended(
              onPressed: () => _open(),
              icon: const Icon(Icons.add),
              label: const Text('New note'),
            ),
      body: WorkspaceBody(
        child: RefreshIndicator(
          onRefresh: widget.onRefresh,
          child: CustomScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverPadding(
                padding: const EdgeInsets.all(16),
                sliver: SliverToBoxAdapter(
                  child: TextField(
                    decoration: const InputDecoration(
                      hintText: 'Search notes',
                      prefixIcon: Icon(Icons.search),
                    ),
                    onChanged: (value) => setState(() => _query = value),
                  ),
                ),
              ),
              if (widget.loading && source.isEmpty)
                const SliverToBoxAdapter(
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (notes.isEmpty)
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: WorkspaceEmptyState(
                    icon: _showTrash
                        ? Icons.delete_outline
                        : Icons.lightbulb_outline,
                    title: _query.isNotEmpty
                        ? 'No matching notes'
                        : _showTrash
                        ? 'Trash is empty'
                        : 'Capture a thought',
                    description: _query.isNotEmpty
                        ? 'Try a different title, detail, or place.'
                        : 'Your ideas and details, together in one place.',
                  ),
                )
              else
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 100),
                  sliver: SliverLayoutBuilder(
                    builder: (context, constraints) {
                      final columns =
                          constraints.crossAxisExtent < 340 ||
                              MediaQuery.textScalerOf(context).scale(14) > 20
                          ? 1
                          : constraints.crossAxisExtent < 650
                          ? 2
                          : 3;
                      return SliverGrid(
                        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: columns,
                          mainAxisExtent: 230,
                          crossAxisSpacing: 12,
                          mainAxisSpacing: 12,
                        ),
                        delegate: SliverChildBuilderDelegate((context, index) {
                          final note = notes[index];
                          final id = note['id'].toString();
                          return Material(
                            color: index.isEven
                                ? AppTheme.surface
                                : AppTheme.surfaceBright,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                              side: const BorderSide(color: AppTheme.border),
                            ),
                            clipBehavior: Clip.antiAlias,
                            child: InkWell(
                              key: ValueKey('note-$id'),
                              onTap: () => _open(note),
                              child: Padding(
                                padding: const EdgeInsets.fromLTRB(
                                  16,
                                  16,
                                  8,
                                  6,
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      noteTitle(note),
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: Theme.of(
                                        context,
                                      ).textTheme.titleMedium,
                                    ),
                                    const SizedBox(height: 8),
                                    Expanded(
                                      child: Text(
                                        (note['content'] ?? '').toString(),
                                        maxLines: 4,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                    Row(
                                      children: [
                                        Expanded(
                                          child: Text(
                                            (note['place'] ?? '').toString(),
                                            maxLines: 1,
                                            overflow: TextOverflow.ellipsis,
                                            style: Theme.of(
                                              context,
                                            ).textTheme.bodySmall,
                                          ),
                                        ),
                                        IconButton(
                                          tooltip: _showTrash
                                              ? 'Restore note'
                                              : 'Delete note',
                                          onPressed: _busy.contains(id)
                                              ? null
                                              : () {
                                                  if (_showTrash) {
                                                    _restore(note);
                                                  } else {
                                                    _delete(note);
                                                  }
                                                },
                                          icon: Icon(
                                            _showTrash
                                                ? Icons.restore
                                                : Icons.delete_outline,
                                            size: 20,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          );
                        }, childCount: notes.length),
                      );
                    },
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoteEditor extends StatefulWidget {
  const _NoteEditor({
    this.note,
    required this.readOnly,
    required this.onSave,
    this.onDelete,
  });
  final Map<String, dynamic>? note;
  final bool readOnly;
  final Future<void> Function(Map<String, dynamic>) onSave;
  final Future<bool> Function()? onDelete;
  @override
  State<_NoteEditor> createState() => _NoteEditorState();
}

class _NoteEditorState extends State<_NoteEditor> {
  late final _title = TextEditingController(
    text: widget.note == null ? '' : noteTitle(widget.note!),
  );
  late final _content = TextEditingController(
    text: widget.note?['content']?.toString() ?? '',
  );
  late final _place = TextEditingController(
    text: widget.note?['place']?.toString() ?? '',
  );
  bool _saving = false;
  bool _deleting = false;
  String? _error;
  @override
  void dispose() {
    _title.dispose();
    _content.dispose();
    _place.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving || _deleting) return;
    if (_title.text.trim().isEmpty && _content.text.trim().isEmpty) {
      setState(() => _error = 'Add a title or a note before saving.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final now = DateTime.now().toUtc().toIso8601String();
    try {
      await widget.onSave({
        ...?widget.note,
        'id':
            widget.note?['id'] ??
            'note-${DateTime.now().microsecondsSinceEpoch}',
        'title': _title.text.trim(),
        'content': _content.text.trim(),
        'place': _place.text.trim(),
        'created_at': widget.note?['created_at'] ?? now,
        'updated_at': now,
      });
      if (mounted) Navigator.pop(context);
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = 'Could not save. Your draft is still here. Try again.';
        });
      }
    }
  }

  Future<void> _close() async {
    if (_saving || _deleting) return;
    final unchanged =
        _title.text == (widget.note == null ? '' : noteTitle(widget.note!)) &&
        _content.text == (widget.note?['content']?.toString() ?? '') &&
        _place.text == (widget.note?['place']?.toString() ?? '');
    if (widget.readOnly ||
        unchanged ||
        (widget.note == null &&
            _title.text.trim().isEmpty &&
            _content.text.trim().isEmpty)) {
      Navigator.pop(context);
    } else {
      await _save();
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: false,
    onPopInvokedWithResult: (didPop, _) {
      if (!didPop) _close();
    },
    child: Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640, maxHeight: 650),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.sticky_note_2_outlined,
                    color: AppTheme.amber,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      widget.readOnly
                          ? 'In Trash'
                          : widget.note == null
                          ? 'New note'
                          : 'Edit note',
                    ),
                  ),
                  IconButton(
                    tooltip: 'Close',
                    onPressed: _saving || _deleting ? null : _close,
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              Expanded(
                child: ListView(
                  children: [
                    TextField(
                      key: const ValueKey('note-title'),
                      controller: _title,
                      readOnly: widget.readOnly || _saving,
                      style: Theme.of(context).textTheme.titleLarge,
                      maxLines: null,
                      decoration: const InputDecoration(
                        hintText: 'Title',
                        border: InputBorder.none,
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      key: const ValueKey('note-content'),
                      controller: _content,
                      readOnly: widget.readOnly || _saving,
                      minLines: 6,
                      maxLines: null,
                      decoration: const InputDecoration(
                        hintText: 'Take a note…',
                        border: InputBorder.none,
                      ),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      key: const ValueKey('note-place'),
                      controller: _place,
                      readOnly: widget.readOnly || _saving,
                      decoration: const InputDecoration(
                        labelText: 'Place or label',
                        prefixIcon: Icon(Icons.label_outline),
                      ),
                    ),
                  ],
                ),
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Text(
                    _error!,
                    style: const TextStyle(color: AppTheme.red),
                  ),
                ),
              Row(
                children: [
                  if (!widget.readOnly && widget.onDelete != null)
                    IconButton(
                      tooltip: 'Delete note',
                      icon: const Icon(Icons.delete_outline),
                      onPressed: _saving || _deleting
                          ? null
                          : () async {
                              setState(() => _deleting = true);
                              if (await widget.onDelete!() && context.mounted) {
                                Navigator.pop(context);
                              } else if (mounted) {
                                setState(() => _deleting = false);
                              }
                            },
                    ),
                  const Spacer(),
                  if (!widget.readOnly)
                    FilledButton(
                      onPressed: _saving || _deleting ? null : _save,
                      child: Text(_saving ? 'Saving…' : 'Save'),
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
