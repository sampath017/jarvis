import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'dart:ui';
import '../../providers/task_provider.dart';
import '../../providers/note_provider.dart';
import '../../providers/chat_provider.dart';
import '../../services/api_service.dart';
import '../../providers/api_provider.dart';

class AskJavrisBar extends ConsumerStatefulWidget {
  const AskJavrisBar({Key? key}) : super(key: key);

  @override
  ConsumerState<AskJavrisBar> createState() => _AskJavrisBarState();
}

class _AskJavrisBarState extends ConsumerState<AskJavrisBar> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  bool _isTyping = false;
  bool _isLoading = false;
  final TextEditingController _textController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    _textController.dispose();
    super.dispose();
  }

  Future<void> _handleSubmit() async {
    final message = _textController.text.trim();
    if (message.isEmpty || _isLoading) return;

    setState(() {
      _isLoading = true;
      _isTyping = false;
    });

    try {
      // Add user message to chat
      await ref.read(chatProvider.notifier).addMessage(message, true);
      _textController.clear();

      final currentThread = ref.read(chatProvider).currentThread!;
      final response = await ref.read(apiServiceProvider).askAI(message, currentThread.id, threadTitle: currentThread.title);
      
      // Add AI response to chat
      await ref.read(chatProvider.notifier).addMessage(response, false);

      // Refresh providers in case AI made changes
      ref.invalidate(taskListProvider);
      ref.invalidate(noteListProvider);
    } catch (e) {
      if (mounted) {
        ref.read(chatProvider.notifier).addMessage("Error: $e", false);
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  void _toggleChat() {
    final isVisible = ref.read(chatProvider).isVisible;
    ref.read(chatProvider.notifier).toggleVisibility(!isVisible);
  }

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(30),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 300),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: const Color(0xFF18181C).withOpacity(0.8),
            borderRadius: BorderRadius.circular(30),
            border: Border.all(
              color: const Color(0xFF2A2A32),
              width: 0.5,
            ),
            boxShadow: [
              BoxShadow(
                color: const Color(0xFF2563EB).withOpacity(0.15),
                blurRadius: 20,
                spreadRadius: -5,
              ),
            ],
          ),
          child: Row(
            children: [
              // Orb
              GestureDetector(
                onTap: _toggleChat,
                child: AnimatedBuilder(
                  animation: _controller,
                  builder: (context, child) {
                    final chatState = ref.watch(chatProvider);
                    return Container(
                      width: 24,
                      height: 24,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        gradient: RadialGradient(
                          colors: [
                            chatState.isVisible ? const Color(0xFF2563EB) : const Color(0xFF3B82F6),
                            const Color(0xFF1E3A8A).withOpacity(0.5),
                          ],
                        ),
                        boxShadow: [
                          BoxShadow(
                            color: const Color(0xFF2563EB).withOpacity(0.5 * _controller.value),
                            blurRadius: 10 * _controller.value,
                            spreadRadius: 2,
                          ),
                        ],
                      ),
                      child: chatState.isVisible && (chatState.currentThread?.messages.isNotEmpty ?? false)
                        ? const Icon(Icons.keyboard_arrow_down, size: 16, color: Colors.white)
                        : null,
                    );
                  },
                ),
              ),
              const SizedBox(width: 12),
              // Text Input
              Expanded(
                child: TextField(
                  controller: _textController,
                  enabled: !_isLoading,
                  style: const TextStyle(color: Color(0xFFF0F0F2), fontSize: 14),
                  decoration: const InputDecoration(
                    hintText: 'Ask Javris...',
                    hintStyle: TextStyle(color: Color(0xFF9CA3AF), fontSize: 14, fontWeight: FontWeight.w500),
                    border: InputBorder.none,
                    isDense: true,
                    contentPadding: EdgeInsets.zero,
                  ),
                  onChanged: (val) {
                    setState(() {
                      _isTyping = val.isNotEmpty;
                    });
                  },
                  onSubmitted: (_) => _handleSubmit(),
                ),
              ),
              // Send Icon
              GestureDetector(
                onTap: _handleSubmit,
                child: AnimatedOpacity(
                  opacity: (_isTyping && !_isLoading) ? 1.0 : 0.5,
                  duration: const Duration(milliseconds: 200),
                  child: Container(
                    padding: const EdgeInsets.all(6),
                    decoration: BoxDecoration(
                      color: (_isTyping && !_isLoading) ? const Color(0xFF2563EB) : Colors.transparent,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      Icons.send_rounded,
                      color: (_isTyping && !_isLoading) ? Colors.white : const Color(0xFF9CA3AF),
                      size: 16,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

