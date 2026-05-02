import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../models/note.dart';
import '../../providers/note_provider.dart';

class NoteDetailsScreen extends ConsumerStatefulWidget {
  final Note note;
  const NoteDetailsScreen({Key? key, required this.note}) : super(key: key);

  @override
  ConsumerState<NoteDetailsScreen> createState() => _NoteDetailsScreenState();
}

class _NoteDetailsScreenState extends ConsumerState<NoteDetailsScreen> {
  late TextEditingController _titleController;
  late TextEditingController _contentController;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.note.title);
    _contentController = TextEditingController(text: widget.note.content);
  }

  @override
  void dispose() {
    _titleController.dispose();
    _contentController.dispose();
    super.dispose();
  }

  void _saveNote() {
    final updatedNote = widget.note.copyWith(
      title: _titleController.text,
      content: _contentController.text,
    );
    // We need an updateNote method in note_provider.dart
    // For now I will just call addNote which will overwrite if ID matches or I can add updateNote
    ref.read(noteListProvider.notifier).addNote(updatedNote); 
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF111114),
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Color(0xFFF0F0F2)),
          onPressed: () {
            _saveNote();
            Navigator.of(context).pop();
          },
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline, color: Colors.redAccent),
            onPressed: () {
              ref.read(noteListProvider.notifier).deleteNote(widget.note.id);
              Navigator.of(context).pop();
            },
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Edited ${DateFormat('MMM d, h:mm a').format(widget.note.createdAt)}',
              style: const TextStyle(color: Color(0xFF555555), fontSize: 12),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _titleController,
              style: const TextStyle(color: Color(0xFFF0F0F2), fontSize: 24, fontWeight: FontWeight.bold),
              decoration: const InputDecoration(
                hintText: 'Title',
                hintStyle: TextStyle(color: Color(0xFF333333)),
                border: InputBorder.none,
              ),
              maxLines: null,
            ),
            const SizedBox(height: 8),
            Expanded(
              child: TextField(
                controller: _contentController,
                style: const TextStyle(color: Color(0xFFA0A0C0), fontSize: 16, height: 1.6),
                decoration: const InputDecoration(
                  hintText: 'Note content...',
                  hintStyle: TextStyle(color: Color(0xFF333333)),
                  border: InputBorder.none,
                ),
                maxLines: null,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
