import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../models/task.dart';
import '../../providers/task_provider.dart';
import '../screens/task_details_screen.dart';

class TaskItem extends ConsumerWidget {
  final Task task;

  const TaskItem({Key? key, required this.task}) : super(key: key);

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
      onTap: () {
        Navigator.of(context).push(
          MaterialPageRoute(builder: (context) => TaskDetailsScreen(task: task)),
        );
      },
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
                child: Container(
                  width: 24,
                  height: 24,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: task.isCompleted ? const Color(0xFF2563EB) : const Color(0xFF555555),
                      width: 2,
                    ),
                    color: task.isCompleted ? const Color(0xFF2563EB) : Colors.transparent,
                  ),
                  child: task.isCompleted
                      ? const Icon(Icons.check, size: 16, color: Colors.white)
                      : null,
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
                      color: task.isCompleted ? const Color(0xFF555555) : const Color(0xFFF0F0F2),
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
