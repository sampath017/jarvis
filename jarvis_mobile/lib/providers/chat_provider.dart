import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import '../models/chat_thread.dart';
import '../services/api_service.dart';
import 'chat_threads_provider.dart';

class ChatState {
  final ChatThread? currentThread;
  final bool isVisible;

  ChatState({
    this.currentThread,
    this.isVisible = false,
  });

  ChatState copyWith({
    ChatThread? currentThread,
    bool? isVisible,
  }) {
    return ChatState(
      currentThread: currentThread ?? this.currentThread,
      isVisible: isVisible ?? this.isVisible,
    );
  }
}

class ChatNotifier extends Notifier<ChatState> {
  final _apiService = ApiService();

  @override
  ChatState build() {
    return ChatState();
  }

  void openChat(ChatThread thread) {
    state = state.copyWith(currentThread: thread, isVisible: true);
  }

  Future<void> addMessage(String text, bool isUser) async {
    final newMessage = ChatMessage(
      text: text,
      isUser: isUser,
      timestamp: DateTime.now(),
    );

    ChatThread thread;
    if (state.currentThread == null) {
      // Create new thread
      thread = ChatThread(
        id: const Uuid().v4(),
        title: text.length > 20 ? '${text.substring(0, 20)}...' : text,
        updatedAt: DateTime.now(),
        messages: [newMessage],
      );
    } else {
      // Append to existing
      thread = ChatThread(
        id: state.currentThread!.id,
        title: state.currentThread!.title,
        updatedAt: DateTime.now(),
        messages: [...state.currentThread!.messages, newMessage],
      );
    }

    state = state.copyWith(currentThread: thread, isVisible: true);
    
    // Save to firebase
    await _apiService.saveChatThread(thread);
    ref.invalidate(chatThreadsProvider); // refresh list
  }

  Future<void> renameThread(String newTitle) async {
    final thread = state.currentThread;
    if (thread != null) {
      final updatedThread = ChatThread(
        id: thread.id,
        title: newTitle,
        updatedAt: DateTime.now(),
        messages: thread.messages,
      );
      
      await _apiService.saveChatThread(updatedThread);
      state = state.copyWith(currentThread: updatedThread);
      ref.invalidate(chatThreadsProvider);
    }
  }

  void toggleVisibility(bool visible) {
    state = state.copyWith(isVisible: visible);
  }

  void startNewChat() {
    state = ChatState(isVisible: true);
  }

  void clearChat() {
    state = ChatState();
  }
}

final chatProvider = NotifierProvider<ChatNotifier, ChatState>(() {
  return ChatNotifier();
});
