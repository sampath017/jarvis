import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'dart:ui';
import '../../providers/chat_provider.dart';
import '../../models/chat_thread.dart';

class ChatHistoryView extends ConsumerWidget {
  const ChatHistoryView({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chatState = ref.watch(chatProvider);
    final messages = chatState.currentThread?.messages ?? [];
    
    if (!chatState.isVisible || messages.isEmpty) {
      return const SizedBox.shrink();
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      constraints: BoxConstraints(
        maxHeight: MediaQuery.of(context).size.height * 0.4,
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
          child: Container(
            decoration: BoxDecoration(
              color: const Color(0xFF18181C).withOpacity(0.7),
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: const Color(0xFF2A2A32), width: 0.5),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _buildHeader(ref),
                Flexible(
                  child: ListView.builder(
                    reverse: true,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    itemCount: messages.length,
                    itemBuilder: (context, index) {
                      final message = messages[messages.length - 1 - index];
                      return _buildMessageBubble(message);
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(WidgetRef ref) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFF2A2A32), width: 0.5)),
      ),
      child: Row(
        children: [
          const Icon(Icons.auto_awesome, color: Color(0xFF2563EB), size: 16),
          const SizedBox(width: 8),
          const Text('Javris Assistant', 
            style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold)
          ),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.add, color: Color(0xFFF0F0F2), size: 16),
            tooltip: 'New Chat',
            onPressed: () {
              ref.read(chatProvider.notifier).clearChat();
              ref.read(chatProvider.notifier).startNewChat();
            },
            constraints: const BoxConstraints(),
            padding: const EdgeInsets.only(right: 16),
          ),
          IconButton(
            icon: const Icon(Icons.close, color: Color(0xFF888888), size: 16),
            tooltip: 'Close',
            onPressed: () => ref.read(chatProvider.notifier).toggleVisibility(false),
            constraints: const BoxConstraints(),
            padding: EdgeInsets.zero,
          ),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(ChatMessage message) {
    return Align(
      alignment: message.isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: message.isUser ? const Color(0xFF2563EB).withOpacity(0.8) : const Color(0xFF2A2A32).withOpacity(0.5),
          borderRadius: BorderRadius.circular(16).copyWith(
            bottomRight: message.isUser ? const Radius.circular(0) : const Radius.circular(16),
            bottomLeft: message.isUser ? const Radius.circular(16) : const Radius.circular(0),
          ),
        ),
        child: MarkdownBody(
          data: message.text,
          styleSheet: MarkdownStyleSheet(
            p: const TextStyle(color: Colors.white, fontSize: 13),
            strong: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold),
          ),
        ),
      ),
    );
  }
}
