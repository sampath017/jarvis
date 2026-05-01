import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers/task_provider.dart';
import '../widgets/task_item.dart';
import '../widgets/add_task_bottom_sheet.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({Key? key}) : super(key: key);

  void _showAddTaskBottomSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => const AddTaskBottomSheet(),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final taskListAsyncValue = ref.watch(taskListProvider);

    return Scaffold(
      backgroundColor: Theme.of(context).colorScheme.surface,
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.surface,
        elevation: 0,
        centerTitle: false,
        title: Row(
          children: [
            Icon(Icons.check_circle, color: Theme.of(context).colorScheme.primary, size: 28),
            const SizedBox(width: 8),
            const Text(
              'Tasks',
              style: TextStyle(fontWeight: FontWeight.w600, fontSize: 24),
            ),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.all(8.0),
            child: CircleAvatar(
              backgroundColor: Theme.of(context).colorScheme.primaryContainer,
              child: const Text('S'),
            ),
          ),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 800),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
                  child: Container(
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.surfaceContainerLow,
                      borderRadius: BorderRadius.circular(24),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(24, 24, 24, 8),
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              const Text(
                                'My Tasks',
                                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                              ),
                              IconButton(
                                icon: const Icon(Icons.more_vert),
                                onPressed: () {},
                              ),
                            ],
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 16.0),
                          child: TextButton.icon(
                            onPressed: () => _showAddTaskBottomSheet(context),
                            icon: const Icon(Icons.add),
                            label: const Text('Add a task'),
                            style: TextButton.styleFrom(
                              foregroundColor: Theme.of(context).colorScheme.primary,
                              textStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                            ),
                          ),
                        ),
                        const SizedBox(height: 8),
                        Expanded(
                          child: taskListAsyncValue.when(
                            data: (tasks) {
                              final activeTasks = tasks.where((t) => !t.isCompleted).toList();
                              final completedTasks = tasks.where((t) => t.isCompleted).toList();

                              if (tasks.isEmpty) {
                                return const Center(child: Text('All tasks completed!'));
                              }

                              return ListView(
                                children: [
                                  ...activeTasks.map((task) => TaskItem(task: task)),
                                  if (completedTasks.isNotEmpty)
                                    ExpansionTile(
                                      title: Text('Completed (${completedTasks.length})'),
                                      children: completedTasks.map((task) => TaskItem(task: task)).toList(),
                                    ),
                                ],
                              );
                            },
                            loading: () => const Center(child: CircularProgressIndicator()),
                            error: (err, stack) => Center(child: Text('Error: $err')),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _showAddTaskBottomSheet(context),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        icon: const Icon(Icons.add),
        label: const Text('Create'),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.startFloat,
    );
  }
}
