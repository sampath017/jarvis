import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../models/task.dart';
import '../../providers/task_provider.dart';

class EditTaskBottomSheet extends ConsumerStatefulWidget {
  final Task task;
  const EditTaskBottomSheet({Key? key, required this.task}) : super(key: key);

  @override
  ConsumerState<EditTaskBottomSheet> createState() => _EditTaskBottomSheetState();
}

class _EditTaskBottomSheetState extends ConsumerState<EditTaskBottomSheet> {
  late TextEditingController _titleController;
  late TextEditingController _notesController;
  late Category _selectedCategory;
  DateTime? _dueDate;
  TimeOfDay? _reminderTime;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.task.title);
    _notesController = TextEditingController(text: widget.task.notes);
    _selectedCategory = widget.task.category;
    _dueDate = widget.task.dueDate;
    if (widget.task.reminderTime != null) {
      _reminderTime = TimeOfDay.fromDateTime(widget.task.reminderTime!);
    }
  }

  @override
  void dispose() {
    _titleController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  void _saveTask() {
    if (_titleController.text.trim().isEmpty) return;

    DateTime? finalReminderTime;
    if (_reminderTime != null) {
      final baseDate = _dueDate ?? DateTime.now();
      finalReminderTime = DateTime(
        baseDate.year,
        baseDate.month,
        baseDate.day,
        _reminderTime!.hour,
        _reminderTime!.minute,
      );
    }

    final updatedTask = widget.task.copyWith(
      title: _titleController.text.trim(),
      notes: _notesController.text.trim(),
      category: _selectedCategory,
      dueDate: _dueDate,
      reminderTime: finalReminderTime,
    );

    ref.read(taskListProvider.notifier).updateTask(updatedTask);
    Navigator.of(context).pop();
  }

  Future<void> _pickDateAndTime() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _dueDate ?? DateTime.now(),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (date != null) {
      setState(() {
        _dueDate = date;
      });
      final time = await showTimePicker(
        context: context,
        initialTime: _reminderTime ?? TimeOfDay.now(),
      );
      if (time != null) {
        setState(() {
          _reminderTime = time;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: Container(
        padding: const EdgeInsets.all(24.0),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'Edit Task',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                ),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(
                hintText: 'Task title',
                border: InputBorder.none,
                hintStyle: TextStyle(fontSize: 20),
              ),
              style: const TextStyle(fontSize: 20),
            ),
            TextField(
              controller: _notesController,
              decoration: const InputDecoration(
                hintText: 'Add details',
                border: InputBorder.none,
              ),
              maxLines: null,
            ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 8,
              children: [
                ActionChip(
                  label: Text(_dueDate == null && _reminderTime == null
                      ? 'Add date/time'
                      : '${_dueDate != null ? "${_dueDate!.month}/${_dueDate!.day}" : ""}${_reminderTime != null ? " ${_reminderTime!.format(context)}" : ""}'),
                  avatar: const Icon(Icons.access_time, size: 16),
                  onPressed: _pickDateAndTime,
                ),
                DropdownButtonHideUnderline(
                  child: DropdownButton<Category>(
                    value: _selectedCategory,
                    items: Category.values.map((cat) {
                      return DropdownMenuItem(
                        value: cat,
                        child: Text(cat.name),
                      );
                    }).toList(),
                    onChanged: (val) {
                      if (val != null) {
                        setState(() {
                          _selectedCategory = val;
                        });
                      }
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                TextButton.icon(
                  onPressed: () {
                    ref.read(taskListProvider.notifier).deleteTask(widget.task.id);
                    Navigator.of(context).pop();
                  },
                  icon: const Icon(Icons.delete_outline, color: Colors.red),
                  label: const Text('Delete', style: TextStyle(color: Colors.red)),
                ),
                FilledButton(
                  onPressed: _saveTask,
                  child: const Text('Save'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
