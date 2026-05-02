import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/task.dart';
import '../services/api_service.dart';

final apiServiceProvider = Provider<ApiService>((ref) {
  return ApiService();
});

final taskListProvider = AsyncNotifierProvider<TaskListNotifier, List<Task>>(() {
  return TaskListNotifier();
});

class TaskListNotifier extends AsyncNotifier<List<Task>> {
  late ApiService _apiService;

  @override
  Future<List<Task>> build() async {
    _apiService = ref.watch(apiServiceProvider);
    return _apiService.fetchTasks();
  }

  Future<void> addTask(Task task) async {
    final previousState = state;
    if (state.hasValue) {
      final existingIndex = state.value!.indexWhere((t) => t.id == task.id);
      if (existingIndex != -1) {
        final newList = List<Task>.from(state.value!);
        newList[existingIndex] = task;
        state = AsyncValue.data(newList);
      } else {
        state = AsyncValue.data([...state.value!, task]);
      }
    }

    try {
      await _apiService.createTask(task);
    } catch (e) {
      // Revert on failure
      state = previousState;
    }
  }

  Future<void> updateTask(Task updatedTask) async {
    final previousState = state;
    if (state.hasValue) {
      final updatedList = state.value!.map((task) {
        if (task.id == updatedTask.id) {
          return updatedTask;
        }
        return task;
      }).toList();
      state = AsyncValue.data(updatedList);
    }

    try {
      await _apiService.updateTask(updatedTask);
    } catch (e) {
      state = previousState;
    }
  }

  Future<void> toggleTaskCompletion(String id) async {
    final previousState = state;
    Task? updatedTask;

    if (state.hasValue) {
      final updatedList = state.value!.map((task) {
        if (task.id == id) {
          updatedTask = task.copyWith(isCompleted: !task.isCompleted);
          return updatedTask!;
        }
        return task;
      }).toList();
      state = AsyncValue.data(updatedList);
    }

    if (updatedTask != null) {
      try {
        await _apiService.updateTask(updatedTask!);
      } catch (e) {
        state = previousState;
      }
    }
  }

  Future<void> deleteTask(String id) async {
    final previousState = state;
    if (state.hasValue) {
      state = AsyncValue.data(state.value!.where((t) => t.id != id).toList());
    }

    try {
      await _apiService.deleteTask(id);
    } catch (e) {
      state = previousState;
    }
  }
}
