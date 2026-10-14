import 'package:flutter/material.dart';
import '../../models/chat_session.dart';

Future<bool> confirmChatArchive(BuildContext context, ChatSession chat) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Archive “${chat.title}”?'),
        content: Text(
          'Move this conversation to Archived on this phone. You can open it and continue later.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Archive'),
          ),
        ],
      ),
    ) ==
    true;
