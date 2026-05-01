import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import '../../models/task.dart';
import '../../providers/task_provider.dart';

class AddTaskBottomSheet extends ConsumerStatefulWidget {
  const AddTaskBottomSheet({Key? key}) : super(key: key);

  @override
  ConsumerState<AddTaskBottomSheet> createState() => _AddTaskBottomSheetState();
}

class _AddTaskBottomSheetState extends ConsumerState<AddTaskBottomSheet> {
  final _titleController = TextEditingController();
  final _notesController = TextEditingController();
  Category _selectedCategory = Category.general;
  DateTime? _dueDate;
  TimeOfDay? _reminderTime;
  bool _showDetails = false;

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

    final newTask = Task(
      id: const Uuid().v4(),
      title: _titleController.text.trim(),
      notes: _notesController.text.trim(),
      category: _selectedCategory,
      dueDate: _dueDate,
      reminderTime: finalReminderTime,
    );

    ref.read(taskListProvider.notifier).addTask(newTask);
    Navigator.of(context).pop();
  }

  Future<void> _pickDateAndTime() async {
    final date = await showDatePicker(
      context: context,
      initialDate: DateTime.now(),
      firstDate: DateTime.now(),
      lastDate: DateTime(2100),
    );
    if (date != null) {
      setState(() {
        _dueDate = date;
      });
      final time = await showTimePicker(
        context: context,
        initialTime: TimeOfDay.now(),
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
            TextField(
              controller: _titleController,
              autofocus: true,
              decoration: const InputDecoration(
                hintText: 'New task',
                border: InputBorder.none,
                hintStyle: TextStyle(fontSize: 20),
              ),
              style: const TextStyle(fontSize: 20),
              onSubmitted: (_) => _saveTask(),
            ),
            if (_showDetails)
              TextField(
                controller: _notesController,
                decoration: const InputDecoration(
                  hintText: 'Add details',
                  border: InputBorder.none,
                ),
                maxLines: null,
                autofocus: true,
              ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                if (_dueDate != null || _reminderTime != null)
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
                          '${_dueDate != null ? "${_dueDate!.month}/${_dueDate!.day}" : ""}${_reminderTime != null ? " ${_reminderTime!.format(context)}" : ""}',
                          style: TextStyle(
                            fontSize: 12,
                            color: Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                        ),
                        const SizedBox(width: 4),
                        InkWell(
                          child: const Icon(Icons.close, size: 14),
                          onTap: () {
                            setState(() {
                              _dueDate = null;
                              _reminderTime = null;
                            });
                          },
                        ),
                      ],
                    ),
                  ),
                if (_selectedCategory != Category.general)
                  ActionChip(
                    label: Text(_selectedCategory.name),
                    onPressed: () {},
                  ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.sort),
                      tooltip: 'Add details',
                      onPressed: () {
                        setState(() {
                          _showDetails = true;
                        });
                      },
                    ),
                    IconButton(
                      icon: const Icon(Icons.event),
                      tooltip: 'Add date/time',
                      onPressed: _pickDateAndTime,
                    ),
                    PopupMenuButton<Category>(
                      icon: const Icon(Icons.label_outline),
                      tooltip: 'Select List/Category',
                      onSelected: (cat) {
                        setState(() {
                          _selectedCategory = cat;
                        });
                      },
                      itemBuilder: (context) => Category.values.map((cat) {
                        return PopupMenuItem(
                          value: cat,
                          child: Text(cat.name),
                        );
                      }).toList(),
                    ),
                  ],
                ),
                TextButton(
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
