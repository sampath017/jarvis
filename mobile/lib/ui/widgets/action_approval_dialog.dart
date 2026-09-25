import 'dart:convert';
import 'package:flutter/material.dart';
import '../theme.dart';

Future<bool> showActionApproval(
  BuildContext context,
  Map<String, dynamic> preview,
) async {
  final operation = preview['operation']?.toString() ?? '';
  final generic = operation == 'approval';
  final drive = operation == 'drive_upload';
  final analysis = operation == 'file_analyze';
  final title = analysis
      ? 'Analyze this saved file?'
      : drive
      ? 'Save this file to Drive & memory?'
      : generic
      ? 'Approve this change?'
      : switch (operation) {
          'create' => 'Create this event?',
          'update' => 'Update this event?',
          'delete' => 'Delete this event?',
          _ => 'Approve calendar change?',
        };
  final label = analysis
      ? 'Allow analysis'
      : drive
      ? 'Save file'
      : generic
      ? 'Approve change'
      : switch (operation) {
          'create' => 'Create event',
          'update' => 'Save changes',
          'delete' => 'Delete event',
          _ => 'Approve',
        };
  final result = await showDialog<bool>(
    context: context,
    barrierDismissible: true,
    builder: (context) => AlertDialog(
      icon: Icon(
        operation == 'delete'
            ? Icons.delete_outline
            : Icons.verified_user_outlined,
        color: AppTheme.primaryLight,
      ),
      title: Text(title),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (analysis) ...[
                SelectableText(
                  preview['name'].toString(),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 12),
                SelectableText('Question: ${preview['question']}'),
                const SizedBox(height: 12),
                Text(
                  'Google account: ${preview['account']}\nModel: ${preview['model']}',
                ),
                const SizedBox(height: 12),
                const Text(
                  'Jarvis will read this original from Drive and send its contents through the Jarvis backend and OpenRouter to the selected model for this question. Firebase retains metadata and the answer, never the raw file. The original stays in Drive.',
                ),
              ] else if (drive) ...[
                SelectableText(
                  preview['name'].toString(),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 12),
                Text(
                  '${preview['mimeType']} · ${((preview['size'] as num) / (1024 * 1024)).toStringAsFixed(1)} MB',
                ),
                const SizedBox(height: 12),
                Text(
                  'Google account: ${preview['account']}\nFolder: ${preview['folder']}',
                ),
                const SizedBox(height: 12),
                SelectableText(
                  'Remember with this description:\n${preview['caption']}',
                ),
                const SizedBox(height: 12),
                const Text(
                  'The original goes to Google Drive. Firebase remembers the name, your description and private file link across chats. File contents are analyzed only after a separate approval.',
                ),
              ] else if (generic) ...[
                Text(
                  preview['tool'].toString().replaceAll('_', ' '),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 12),
                for (final entry
                    in (preview['arguments'] as Map? ?? {}).entries)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: SelectableText(
                      '${entry.key.toString().replaceAll('_', ' ')}: ${entry.value is Map || entry.value is List ? const JsonEncoder.withIndent('  ').convert(entry.value) : entry.value}',
                    ),
                  ),
              ] else ...[
                Text(
                  'Google Calendar · ${preview['calendar']}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 16),
                if (operation == 'update') ...[
                  const Text(
                    'Current event',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  _EventDetails(
                    event: Map<String, dynamic>.from(preview['before']),
                  ),
                  const Divider(height: 24),
                  Text(
                    'Proposed changes · ${(preview['changed_fields'] as List).join(', ')}',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ],
                _EventDetails(
                  event: Map<String, dynamic>.from(
                    preview[operation == 'delete' ? 'before' : 'after'],
                  ),
                ),
                if (preview['whole_series'] == true) ...[
                  const SizedBox(height: 12),
                  const Text(
                    'This affects the entire recurring series.',
                    style: TextStyle(color: AppTheme.amber),
                  ),
                ],
                if ((preview['guests'] as List? ?? []).isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(
                    operation == 'delete'
                        ? 'Cancellation notices will be sent to guests:'
                        : 'Invitations or update notices will be sent to guests:',
                  ),
                  SelectableText((preview['guests'] as List).join('\n')),
                ],
                if (operation == 'delete') ...[
                  const SizedBox(height: 12),
                  const Text('This removes the event from Google Calendar.'),
                ],
              ],
              const SizedBox(height: 16),
              const Text(
                'Only this change is approved. Future changes will ask again.',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: const Text('Decline'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, true),
          child: Text(label),
        ),
      ],
    ),
  );
  return result == true;
}

class _EventDetails extends StatelessWidget {
  const _EventDetails({required this.event});
  final Map<String, dynamic> event;
  String _time(dynamic raw) {
    if (raw is! Map) return 'Unspecified';
    return raw['date']?.toString() ??
        '${raw['dateTime']}${raw['timeZone'] == null ? '' : ' (${raw['timeZone']})'}';
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const SizedBox(height: 8),
      SelectableText(
        event['summary']?.toString() ?? '(Untitled event)',
        style: Theme.of(context).textTheme.titleMedium,
      ),
      const SizedBox(height: 8),
      SelectableText(
        'Start: ${_time(event['start'])}\nEnd: ${_time(event['end'])}',
      ),
      if ((event['start'] as Map?)?['date'] != null)
        const Text(
          'All-day event · end date is exclusive.',
          style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
        ),
      for (final key in ['location', 'description', 'attendees', 'recurrence'])
        if (event[key] != null && event[key].toString().isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: SelectableText(
              '$key: ${key == 'attendees' ? (event[key] as List).map((a) => (a as Map)['email']).join(', ') : event[key]}',
            ),
          ),
    ],
  );
}
