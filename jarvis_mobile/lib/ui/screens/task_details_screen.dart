import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../models/task.dart';
import '../../providers/task_provider.dart';

class TaskDetailsScreen extends ConsumerStatefulWidget {
  final Task task;
  const TaskDetailsScreen({Key? key, required this.task}) : super(key: key);

  @override
  ConsumerState<TaskDetailsScreen> createState() => _TaskDetailsScreenState();
}

class _TaskDetailsScreenState extends ConsumerState<TaskDetailsScreen> {
  late TextEditingController _titleController;
  late TextEditingController _notesController;
  late Task _currentTask;

  @override
  void initState() {
    super.initState();
    _currentTask = widget.task;
    _titleController = TextEditingController(text: _currentTask.title);
    _notesController = TextEditingController(text: _currentTask.notes);
  }

  @override
  void dispose() {
    _titleController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  void _updateTask() {
    final updatedTask = _currentTask.copyWith(
      title: _titleController.text,
      notes: _notesController.text,
    );
    ref.read(taskListProvider.notifier).updateTask(updatedTask);
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
          onPressed: () => Navigator.of(context).pop(),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline, color: Colors.redAccent),
            onPressed: () {
              ref.read(taskListProvider.notifier).deleteTask(_currentTask.id);
              Navigator.of(context).pop();
            },
          ),
          TextButton(
            onPressed: () {
              _updateTask();
              Navigator.of(context).pop();
            },
            child: const Text('Save', style: TextStyle(color: Color(0xFF2563EB), fontWeight: FontWeight.bold)),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title
            Row(
              children: [
                Container(
                  width: 24,
                  height: 24,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: _currentTask.isCompleted ? const Color(0xFF2563EB) : const Color(0xFF555555),
                      width: 2,
                    ),
                    color: _currentTask.isCompleted ? const Color(0xFF2563EB) : Colors.transparent,
                  ),
                  child: _currentTask.isCompleted
                      ? const Icon(Icons.check, size: 16, color: Colors.white)
                      : null,
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: _titleController,
                    style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600, color: Color(0xFFF0F0F2)),
                    decoration: const InputDecoration(border: InputBorder.none, hintText: 'Task Title'),
                    maxLines: null,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 32),
            // Details
            _buildDetailRow(Icons.notes, 'Add details', 
              child: TextField(
                controller: _notesController,
                style: const TextStyle(color: Color(0xFFA0A0C0), fontSize: 16),
                decoration: const InputDecoration(border: InputBorder.none, hintText: 'Notes'),
                maxLines: null,
              ),
            ),
            const Divider(color: Color(0xFF222222), height: 32),
            // Date/Time
            _buildDetailRow(Icons.event_outlined, 'Deadline', 
              child: Text(
                _currentTask.dueDate != null 
                  ? DateFormat('EEEE, MMM d, h:mm a').format(_currentTask.dueDate!)
                  : 'Set deadline',
                style: const TextStyle(color: Color(0xFFF0F0F2)),
              ),
              onTap: () async {
                final date = await showDatePicker(
                  context: context,
                  initialDate: _currentTask.dueDate ?? DateTime.now(),
                  firstDate: DateTime.now().subtract(const Duration(days: 365)),
                  lastDate: DateTime(2100),
                );
                if (date != null) {
                  final time = await showTimePicker(
                    context: context,
                    initialTime: TimeOfDay.fromDateTime(_currentTask.dueDate ?? DateTime.now()),
                  );
                  if (time != null) {
                    setState(() {
                      _currentTask = _currentTask.copyWith(
                        dueDate: DateTime(date.year, date.month, date.day, time.hour, time.minute),
                      );
                    });
                  }
                }
              }
            ),
            const Divider(color: Color(0xFF222222), height: 32),
            _buildDetailRow(Icons.notifications_active_outlined, 'Reminder', 
              child: Text(
                _currentTask.reminderTime != null 
                  ? DateFormat('EEEE, MMM d, h:mm a').format(_currentTask.reminderTime!)
                  : 'Set reminder',
                style: const TextStyle(color: Color(0xFFF0F0F2)),
              ),
              onTap: () async {
                final date = await showDatePicker(
                  context: context,
                  initialDate: _currentTask.reminderTime ?? DateTime.now(),
                  firstDate: DateTime.now().subtract(const Duration(days: 365)),
                  lastDate: DateTime(2100),
                );
                if (date != null) {
                  final time = await showTimePicker(
                    context: context,
                    initialTime: TimeOfDay.fromDateTime(_currentTask.reminderTime ?? DateTime.now()),
                  );
                  if (time != null) {
                    setState(() {
                      _currentTask = _currentTask.copyWith(
                        reminderTime: DateTime(date.year, date.month, date.day, time.hour, time.minute),
                      );
                    });
                  }
                }
              }
            ),
            const SizedBox(height: 16),
            if (_currentTask.hasLocationReminder) ...[
              const SizedBox(height: 16),
              _buildDetailRow(Icons.location_on, 'Location Reminder',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _currentTask.locationName ?? 'Unknown',
                      style: const TextStyle(color: Color(0xFFF0F0F2), fontSize: 16, fontWeight: FontWeight.w500),
                    ),
                    const SizedBox(height: 4),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: const Color(0xFF1E3A5F),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        _currentTask.triggerType == LocationTrigger.onExit
                            ? '🔔 Notify when I LEAVE'
                            : '🔔 Notify when I ARRIVE',
                        style: const TextStyle(color: Color(0xFF93C5FD), fontSize: 12),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildDetailRow(IconData icon, String label, {required Widget child, VoidCallback? onTap}) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: const Color(0xFF888888), size: 24),
            const SizedBox(width: 24),
            Expanded(child: child),
          ],
        ),
      ),
    );
  }
}
