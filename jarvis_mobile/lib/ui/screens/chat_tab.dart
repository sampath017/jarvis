import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import '../../providers/chat_provider.dart';
import '../../providers/chat_threads_provider.dart';
import '../../providers/api_provider.dart';
import '../../providers/task_provider.dart';
import '../../providers/note_provider.dart';
import '../../models/chat_thread.dart';

class ChatTab extends ConsumerStatefulWidget {
  const ChatTab({Key? key}) : super(key: key);

  @override
  ConsumerState<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends ConsumerState<ChatTab> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  bool _isTyping = false;
  bool _isLoading = false;

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
      );
    }
  }

  Future<void> _handleSubmit() async {
    final message = _textController.text.trim();
    if (message.isEmpty || _isLoading) return;

    setState(() {
      _isLoading = true;
      _isTyping = false;
    });

    try {
      await ref.read(chatProvider.notifier).addMessage(message, true);
      _textController.clear();
      _scrollToBottom();

      final currentThread = ref.read(chatProvider).currentThread!;
      final response = await ref.read(apiServiceProvider).askAI(
        message, 
        currentThread.id, 
        threadTitle: currentThread.title
      );
      
      await ref.read(chatProvider.notifier).addMessage(response, false);
      _scrollToBottom();

      ref.invalidate(taskListProvider);
      ref.invalidate(noteListProvider);
    } catch (e) {
      if (mounted) {
        ref.read(chatProvider.notifier).addMessage("Error: $e", false);
        _scrollToBottom();
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  void _showRenameDialog(ChatThread thread) {
    final controller = TextEditingController(text: thread.title);
    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          backgroundColor: const Color(0xFF18181C),
          title: const Text('Rename Chat Session', style: TextStyle(color: Colors.white, fontSize: 16)),
          content: TextField(
            controller: controller,
            style: const TextStyle(color: Colors.white),
            decoration: const InputDecoration(
              hintText: 'Enter new name',
              hintStyle: TextStyle(color: Colors.grey),
              enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Color(0xFF333333))),
              focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: Color(0xFF2563EB))),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel', style: TextStyle(color: Colors.grey)),
            ),
            TextButton(
              onPressed: () {
                if (controller.text.trim().isNotEmpty) {
                  if (ref.read(chatProvider).currentThread?.id == thread.id) {
                    ref.read(chatProvider.notifier).renameThread(controller.text.trim());
                  } else {
                    final updatedThread = ChatThread(
                      id: thread.id,
                      title: controller.text.trim(),
                      updatedAt: DateTime.now(),
                      messages: thread.messages,
                    );
                    ref.read(apiServiceProvider).saveChatThread(updatedThread).then((_) {
                      ref.invalidate(chatThreadsProvider);
                    });
                  }
                }
                Navigator.pop(context);
              },
              child: const Text('Save', style: TextStyle(color: Color(0xFF2563EB))),
            ),
          ],
        );
      },
    );
  }

  void _deleteThread(String id) async {
    await ref.read(apiServiceProvider).deleteChatThread(id);
    ref.invalidate(chatThreadsProvider);
    if (ref.read(chatProvider).currentThread?.id == id) {
      ref.read(chatProvider.notifier).clearChat();
    }
  }

  Widget _buildHistoryList() {
    final threadsAsync = ref.watch(chatThreadsProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.all(16.0),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('Recent Chats', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
              ElevatedButton.icon(
                onPressed: () {
                  ref.read(chatProvider.notifier).clearChat();
                  ref.read(chatProvider.notifier).startNewChat();
                },
                icon: const Icon(Icons.add, size: 16),
                label: const Text('New Chat'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF2563EB),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: threadsAsync.when(
            data: (threads) {
              if (threads.isEmpty) {
                return const Center(child: Text('No recent chats', style: TextStyle(color: Color(0xFF555555))));
              }
              return ListView.builder(
                itemCount: threads.length,
                itemBuilder: (context, index) {
                  final thread = threads[index];
                  return ListTile(
                    leading: const Icon(Icons.chat_bubble_outline, color: Color(0xFF888888)),
                    title: Text(thread.title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w500)),
                    subtitle: Text('${thread.messages.length} messages', style: const TextStyle(color: Color(0xFF888888), fontSize: 12)),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          icon: const Icon(Icons.edit, color: Color(0xFF888888), size: 18),
                          onPressed: () => _showRenameDialog(thread),
                        ),
                        IconButton(
                          icon: const Icon(Icons.delete_outline, color: Colors.redAccent, size: 18),
                          onPressed: () => _deleteThread(thread.id),
                        ),
                      ],
                    ),
                    onTap: () {
                      ref.read(chatProvider.notifier).openChat(thread);
                    },
                  );
                },
              );
            },
            loading: () => const Center(child: CircularProgressIndicator(strokeWidth: 2)),
            error: (err, stack) => const Center(child: Text('Error loading chats', style: TextStyle(color: Colors.red))),
          ),
        ),
      ],
    );
  }

  Widget _buildActiveChat() {
    final chatState = ref.watch(chatProvider);
    final messages = chatState.currentThread?.messages ?? [];

    return Column(
      children: [
        // Header
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: Color(0xFF2A2A32), width: 0.5)),
          ),
          child: Row(
            children: [
              IconButton(
                icon: const Icon(Icons.arrow_back, color: Color(0xFFF0F0F2)),
                onPressed: () {
                  ref.read(chatProvider.notifier).clearChat();
                },
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  chatState.currentThread?.title ?? 'New Chat',
                  style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              IconButton(
                icon: const Icon(Icons.add, color: Color(0xFF2563EB)),
                tooltip: 'New Chat',
                onPressed: () {
                  ref.read(chatProvider.notifier).clearChat();
                  ref.read(chatProvider.notifier).startNewChat();
                },
              ),
            ],
          ),
        ),
        
        // Messages list
        Expanded(
          child: ListView.builder(
            controller: _scrollController,
            padding: const EdgeInsets.all(16),
            itemCount: messages.length + (_isLoading ? 1 : 0),
            itemBuilder: (context, index) {
              if (index == messages.length) {
                return const Align(
                  alignment: Alignment.centerLeft,
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: 8),
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                );
              }
              final message = messages[index];
              return _buildMessageBubble(message);
            },
          ),
        ),

        // Input Area
        Container(
          padding: const EdgeInsets.all(16),
          decoration: const BoxDecoration(
            color: Color(0xFF18181C),
            border: Border(top: BorderSide(color: Color(0xFF2A2A32), width: 0.5)),
          ),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _textController,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                  decoration: InputDecoration(
                    hintText: 'Ask Javris...',
                    hintStyle: const TextStyle(color: Color(0xFF888888), fontSize: 14),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(24),
                      borderSide: BorderSide.none,
                    ),
                    filled: true,
                    fillColor: const Color(0xFF2A2A32),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  ),
                  onChanged: (val) {
                    setState(() {
                      _isTyping = val.isNotEmpty;
                    });
                  },
                  onSubmitted: (_) => _handleSubmit(),
                ),
              ),
              const SizedBox(width: 8),
              GestureDetector(
                onTap: _handleSubmit,
                child: AnimatedOpacity(
                  opacity: (_isTyping && !_isLoading) ? 1.0 : 0.5,
                  duration: const Duration(milliseconds: 200),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: (_isTyping && !_isLoading) ? const Color(0xFF2563EB) : Colors.transparent,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      Icons.send_rounded,
                      color: (_isTyping && !_isLoading) ? Colors.white : const Color(0xFF9CA3AF),
                      size: 20,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildMessageBubble(ChatMessage message) {
    final bubble = Container(
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: message.isUser 
          ? const EdgeInsets.symmetric(horizontal: 18, vertical: 12)
          : const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        color: message.isUser ? const Color(0xFF2A2A32) : Colors.transparent,
        borderRadius: BorderRadius.circular(24),
      ),
      child: MarkdownBody(
        data: message.text,
        selectable: true,
        styleSheet: MarkdownStyleSheet(
          p: const TextStyle(color: Colors.white, fontSize: 15, height: 1.5),
          strong: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold),
          code: const TextStyle(color: Color(0xFFE2E8F0), backgroundColor: Color(0xFF18181C), fontFamily: 'monospace'),
          codeblockDecoration: BoxDecoration(
            color: const Color(0xFF18181C),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: const Color(0xFF333333)),
          ),
        ),
      ),
    );

    if (message.isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.8),
          child: bubble,
        ),
      );
    } else {
      return Align(
        alignment: Alignment.centerLeft,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.95),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              bubble,
              Padding(
                padding: const EdgeInsets.only(left: 0.0, top: 4.0, bottom: 12.0),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    InkWell(
                      borderRadius: BorderRadius.circular(4),
                      onTap: () {
                        Clipboard.setData(ClipboardData(text: message.text));
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('Copied to clipboard'), 
                            duration: Duration(seconds: 2),
                            backgroundColor: Color(0xFF2A2A32),
                          ),
                        );
                      },
                      child: const Padding(
                        padding: EdgeInsets.all(4.0),
                        child: Icon(Icons.copy, size: 16, color: Color(0xFF888888)),
                      ),
                    ),
                    const SizedBox(width: 8),
                    InkWell(
                      borderRadius: BorderRadius.circular(4),
                      onTap: () async {
                        final threadId = ref.read(chatProvider).currentThread?.id;
                        if (threadId != null) {
                          try {
                            await ref.read(apiServiceProvider).submitFeedback(threadId, 1);
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('Feedback submitted'), backgroundColor: Color(0xFF2A2A32), duration: Duration(seconds: 2)),
                            );
                          } catch (_) {}
                        }
                      },
                      child: const Padding(
                        padding: EdgeInsets.all(4.0),
                        child: Icon(Icons.thumb_up_alt_outlined, size: 16, color: Color(0xFF888888)),
                      ),
                    ),
                    const SizedBox(width: 8),
                    InkWell(
                      borderRadius: BorderRadius.circular(4),
                      onTap: () async {
                        final threadId = ref.read(chatProvider).currentThread?.id;
                        if (threadId != null) {
                          try {
                            await ref.read(apiServiceProvider).submitFeedback(threadId, -1);
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('Feedback submitted'), backgroundColor: Color(0xFF2A2A32), duration: Duration(seconds: 2)),
                            );
                          } catch (_) {}
                        }
                      },
                      child: const Padding(
                        padding: EdgeInsets.all(4.0),
                        child: Icon(Icons.thumb_down_alt_outlined, size: 16, color: Color(0xFF888888)),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final chatState = ref.watch(chatProvider);
    final isChatActive = chatState.currentThread != null || chatState.isVisible;
    return !isChatActive ? _buildHistoryList() : _buildActiveChat();
  }
}
