import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../models/note.dart';

class NoteCard extends StatelessWidget {
  final Note note;
  final VoidCallback? onTap;

  const NoteCard({Key? key, required this.note, this.onTap}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFF1A1A22),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: const Color(0xFF28283A), width: 0.5),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              note.title.isEmpty ? 'Untitled Note' : note.title,
              style: const TextStyle(color: Color(0xFFF0F0F2), fontSize: 16, fontWeight: FontWeight.bold),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            if (note.content.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                note.content,
                style: const TextStyle(color: Color(0xFF888899), fontSize: 14, height: 1.5),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
            ],
            const SizedBox(height: 12),
            Text(
              DateFormat('MMM d, h:mm a').format(note.createdAt),
              style: const TextStyle(color: Color(0xFF555555), fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }
}
