import 'package:flutter_riverpod/flutter_riverpod.dart';

class ChatMessage {
  final String text;
  final bool isUser;
  final DateTime timestamp;

  ChatMessage({
    required this.text,
    required this.isUser,
    required this.timestamp,
  });
}

class ChatState {
  final List<ChatMessage> messages;
  final bool isVisible;

  ChatState({
    this.messages = const [],
    this.isVisible = false,
  });

  ChatState copyWith({
    List<ChatMessage>? messages,
    bool? isVisible,
  }) {
    return ChatState(
      messages: messages ?? this.messages,
      isVisible: isVisible ?? this.isVisible,
    );
  }
}

class ChatNotifier extends Notifier<ChatState> {
  @override
  ChatState build() {
    return ChatState();
  }

  void addMessage(String text, bool isUser) {
    final newMessage = ChatMessage(
      text: text,
      isUser: isUser,
      timestamp: DateTime.now(),
    );
    state = state.copyWith(
      messages: [...state.messages, newMessage],
      isVisible: true,
    );
  }

  void toggleVisibility(bool visible) {
    state = state.copyWith(isVisible: visible);
  }

  void clearChat() {
    state = ChatState();
  }
}

final chatProvider = NotifierProvider<ChatNotifier, ChatState>(() {
  return ChatNotifier();
});
