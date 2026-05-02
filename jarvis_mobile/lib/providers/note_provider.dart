import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/note.dart';
import '../services/api_service.dart';
import 'task_provider.dart';

final noteListProvider = AsyncNotifierProvider<NoteListNotifier, List<Note>>(() {
  return NoteListNotifier();
});

class NoteListNotifier extends AsyncNotifier<List<Note>> {
  late ApiService _apiService;

  @override
  Future<List<Note>> build() async {
    _apiService = ref.watch(apiServiceProvider);
    return _apiService.fetchNotes();
  }

  Future<void> addNote(Note note) async {
    final previousState = state;
    if (state.hasValue) {
      final existingIndex = state.value!.indexWhere((n) => n.id == note.id);
      if (existingIndex != -1) {
        // Update existing note in list
        final newList = List<Note>.from(state.value!);
        newList[existingIndex] = note;
        state = AsyncValue.data(newList);
      } else {
        // Add new note to list
        state = AsyncValue.data([note, ...state.value!]);
      }
    }

    try {
      await _apiService.createNote(note);
    } catch (e) {
      state = previousState;
    }
  }

  Future<void> deleteNote(String id) async {
    final previousState = state;
    if (state.hasValue) {
      state = AsyncValue.data(state.value!.where((n) => n.id != id).toList());
    }

    try {
      await _apiService.deleteNote(id);
    } catch (e) {
      state = previousState;
    }
  }
}
