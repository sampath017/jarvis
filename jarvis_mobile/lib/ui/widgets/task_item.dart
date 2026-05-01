import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../models/task.dart';
import '../../providers/task_provider.dart';
import 'edit_task_bottom_sheet.dart';

class TaskItem extends ConsumerWidget {
  final Task task;

  const TaskItem({Key? key, required this.task}) : super(key: key);

  void _showEditSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => EditTaskBottomSheet(task: task),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    String? dateTimeStr;
    if (task.dueDate != null) {
      final dateStr = DateFormat('E, MMM d').format(task.dueDate!);
      if (task.reminderTime != null) {
        final timeStr = DateFormat('h:mm a').format(task.reminderTime!);
        dateTimeStr = '$dateStr, $timeStr';
      } else {
        dateTimeStr = dateStr;
      }
    } else if (task.reminderTime != null) {
      dateTimeStr = DateFormat('h:mm a').format(task.reminderTime!);
    }

    return InkWell(
      onTap: () => _showEditSheet(context),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 12.0),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            InkWell(
              onTap: () {
                ref.read(taskListProvider.notifier).toggleTaskCompletion(task.id);
              },
              customBorder: const CircleBorder(),
              child: Padding(
                padding: const EdgeInsets.all(4.0),
                child: Icon(
                  task.isCompleted ? Icons.check_circle : Icons.radio_button_unchecked,
                  color: task.isCompleted ? Theme.of(context).colorScheme.primary : Theme.of(context).colorScheme.onSurfaceVariant,
                  size: 28,
                ),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 4),
                  Text(
                    task.title,
                    style: TextStyle(
                      fontSize: 16,
                      decoration: task.isCompleted ? TextDecoration.lineThrough : null,
                      color: task.isCompleted ? Theme.of(context).colorScheme.onSurfaceVariant : Theme.of(context).colorScheme.onSurface,
                    ),
                  ),
                  if (task.notes.isNotEmpty || dateTimeStr != null || task.category != Category.general)
                    const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    children: [
                      if (dateTimeStr != null)
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
                            borderRadius: BorderRadius.circular(16),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.event, size: 14, color: Theme.of(context).colorScheme.onSurfaceVariant),
                              const SizedBox(width: 4),
                              Text(
                                dateTimeStr,
                                style: TextStyle(
                                  fontSize: 12,
                                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ],
                          ),
                        ),
                      if (task.category != Category.general)
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            color: Theme.of(context).colorScheme.secondaryContainer,
                            borderRadius: BorderRadius.circular(16),
                          ),
                          child: Text(
                            task.category.name,
                            style: TextStyle(
                              fontSize: 12,
                              color: Theme.of(context).colorScheme.onSecondaryContainer,
                            ),
                          ),
                        ),
                      if (task.notes.isNotEmpty)
                        Container(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                            task.notes,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              fontSize: 14,
                            ),
                          ),
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
