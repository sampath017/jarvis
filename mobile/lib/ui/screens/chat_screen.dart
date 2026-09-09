import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:intl/intl.dart';
import '../../models/chat_session.dart';
import '../../services/api_service.dart';
import '../../services/chat_storage_service.dart';
import '../../services/sensor_service.dart';
import '../theme.dart';

/// ChatGPT-like Conversational Agent Screen:
/// Features multi-session conversation history, rename/edit chat titles,
/// delete chats, auto-naming, and full local persistence.
class ChatScreen extends StatefulWidget {
  final SensorService sensorService;

  const ChatScreen({super.key, required this.sensorService});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();
  final ApiService _apiService = ApiService();
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  bool _isSending = false;
  bool _isLoadingSessions = true;

  List<ChatSession> _sessions = [];
  ChatSession? _currentSession;

  @override
  void initState() {
    super.initState();
    _apiService.addListener(_onServiceUpdate);
    _initChat();
  }

  Future<void> _initChat() async {
    await _loadSessions();
    // Non-blocking health check in background
    _apiService.checkHealth();
  }

  void _onServiceUpdate() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _apiService.removeListener(_onServiceUpdate);
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadSessions() async {
    final loaded = await ChatStorageService.loadSessions();
    if (loaded.isEmpty) {
      final initial = _createDefaultSession();
      await ChatStorageService.saveSession(initial);
      _sessions = [initial];
      _currentSession = initial;
    } else {
      _sessions = loaded;
      _currentSession = loaded.first;
    }
    if (mounted) {
      setState(() {
        _isLoadingSessions = false;
      });
      _scrollToBottom();
    }
  }

  ChatSession _createDefaultSession() {
    return ChatSession(
      title: 'New Chat',
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      messages: [],
    );
  }

  Future<void> _startNewChat() async {
    final newSession = ChatSession(
      title: 'New Chat',
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      messages: [],
    );

    setState(() {
      _sessions.insert(0, newSession);
      _currentSession = newSession;
    });

    await ChatStorageService.saveSession(newSession);

    if (_scaffoldKey.currentState?.isDrawerOpen ?? false) {
      _scaffoldKey.currentState?.closeDrawer();
    }

    _scrollToBottom();
  }

  void _selectSession(ChatSession session) {
    setState(() {
      _currentSession = session;
    });
    if (_scaffoldKey.currentState?.isDrawerOpen ?? false) {
      _scaffoldKey.currentState?.closeDrawer();
    }
    _scrollToBottom();
  }

  Future<void> _showRenameDialog(ChatSession session) async {
    final controller = TextEditingController(text: session.title);
    final formKey = GlobalKey<FormState>();

    final updated = await showDialog<String>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: AppTheme.surface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(color: AppTheme.border),
          ),
          title: const Row(
            children: [
              Icon(Icons.edit_note_rounded, color: AppTheme.primary, size: 22),
              SizedBox(width: 8),
              Text(
                'Rename Chat',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  color: AppTheme.textPrimary,
                ),
              ),
            ],
          ),
          content: Form(
            key: formKey,
            child: TextFormField(
              controller: controller,
              autofocus: true,
              style: const TextStyle(color: AppTheme.textPrimary, fontSize: 14),
              decoration: InputDecoration(
                hintText: 'Enter new title...',
                hintStyle: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                filled: true,
                fillColor: AppTheme.surfaceBright,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: AppTheme.border),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: AppTheme.primary),
                ),
              ),
              validator: (v) =>
                  (v == null || v.trim().isEmpty) ? 'Title cannot be empty' : null,
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('Cancel', style: TextStyle(color: AppTheme.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.primary,
                foregroundColor: Colors.black,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
              onPressed: () {
                if (formKey.currentState?.validate() ?? false) {
                  Navigator.of(ctx).pop(controller.text.trim());
                }
              },
              child: const Text('Save', style: TextStyle(fontWeight: FontWeight.bold)),
            ),
          ],
        );
      },
    );

    if (updated != null && updated.isNotEmpty && updated != session.title) {
      setState(() {
        session.title = updated;
        session.updatedAt = DateTime.now();
      });
      await ChatStorageService.renameSession(session.id, updated);
    }
  }

  Future<void> _confirmDeleteSession(ChatSession session) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: AppTheme.surface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(color: AppTheme.border),
          ),
          title: const Row(
            children: [
              Icon(Icons.delete_forever_rounded, color: AppTheme.red, size: 22),
              SizedBox(width: 8),
              Text(
                'Delete Chat',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  color: AppTheme.textPrimary,
                ),
              ),
            ],
          ),
          content: Text(
            'Are you sure you want to delete "${session.title}"?\nThis cannot be undone.',
            style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13, height: 1.4),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Cancel', style: TextStyle(color: AppTheme.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.red,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Delete', style: TextStyle(fontWeight: FontWeight.bold)),
            ),
          ],
        );
      },
    );

    if (confirmed == true) {
      await ChatStorageService.deleteSession(session.id);
      setState(() {
        _sessions.removeWhere((s) => s.id == session.id);
        if (_currentSession?.id == session.id) {
          if (_sessions.isNotEmpty) {
            _currentSession = _sessions.first;
          } else {
            final def = _createDefaultSession();
            _sessions = [def];
            _currentSession = def;
            ChatStorageService.saveSession(def);
          }
        }
      });
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _handleSendMessage(String text) async {
    final query = text.trim();
    if (query.isEmpty || _currentSession == null) return;

    _inputController.clear();

    // Auto-generate title for first user prompt if still "New Chat"
    final isNewChat = _currentSession!.title == 'New Chat';
    if (isNewChat) {
      String smartTitle = query;
      if (smartTitle.length > 28) {
        smartTitle = '${smartTitle.substring(0, 28).trim()}...';
      }
      _currentSession!.title = smartTitle;
    }

    final recentMsgs = _currentSession!.messages;
    final historyPayload = recentMsgs.length > 8
        ? recentMsgs.sublist(recentMsgs.length - 8)
        : recentMsgs;
    final historyList = historyPayload
        .map((m) => <String, dynamic>{
              'role': m.isUser ? 'user' : 'assistant',
              'content': m.text,
            })
        .toList();

    final userMsgId = 'msg_${DateTime.now().microsecondsSinceEpoch}';
    final userMsg = ChatMessage(
      id: userMsgId,
      text: query,
      isUser: true,
      timestamp: DateTime.now(),
    );

    setState(() {
      _currentSession!.messages.add(userMsg);
      _currentSession!.updatedAt = DateTime.now();
      _isSending = true;
    });

    await ChatStorageService.saveSession(_currentSession!);
    _scrollToBottom();

    // Check location accessibility and retrieve current GPS coordinates
    double? lat;
    double? lon;
    try {
      final coords = await widget.sensorService.getCurrentLocation(requestIfNeeded: true);
      if (coords != null) {
        lat = coords['latitude'];
        lon = coords['longitude'];
      } else {
        // If query asks for location and service is disabled, prompt user to open settings
        final isLocationQuery = query.toLowerCase().contains('location') ||
            query.toLowerCase().contains('where am i') ||
            query.toLowerCase().contains('where i am') ||
            query.toLowerCase().contains('place');
        final serviceEnabled = await Geolocator.isLocationServiceEnabled();
        if (!serviceEnabled && isLocationQuery && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('Location services are turned off on your device.'),
              action: SnackBarAction(
                label: 'Settings',
                onPressed: () => Geolocator.openLocationSettings(),
              ),
              duration: const Duration(seconds: 6),
            ),
          );
        }
      }
    } catch (e) {
      debugPrint('[ChatScreen] Error acquiring location for chat: $e');
    }

    final stopwatch = Stopwatch()..start();
    final res = await _apiService.sendCommand(
      query,
      threadId: _currentSession!.id,
      history: historyList,
      latitude: lat,
      longitude: lon,
      requestId: userMsgId,
    );
    stopwatch.stop();
    final durationMs = stopwatch.elapsedMilliseconds;

    if (mounted) {
      ChatMessage botMsg;
      if (res != null && res['status'] == 'ok') {
        final botMsgId = res['run_id'] ?? 'bot_${DateTime.now().microsecondsSinceEpoch}';
        botMsg = ChatMessage(
          id: botMsgId,
          text: res['message'] ?? 'Action executed successfully.',
          isUser: false,
          timestamp: DateTime.now(),
          runId: res['run_id'],
          executedRecords: List<String>.from(res['changed_records'] ?? []),
          durationMs: durationMs,
        );
      } else {
        final errText = res?['error']?.toString() ?? 'Unable to complete action due to connection error';
        botMsg = ChatMessage(
          id: 'err_${DateTime.now().microsecondsSinceEpoch}',
          text: errText,
          isUser: false,
          timestamp: DateTime.now(),
          durationMs: durationMs,
        );
      }

      setState(() {
        _currentSession!.messages.add(botMsg);
        _currentSession!.updatedAt = DateTime.now();
        _isSending = false;
      });

      await ChatStorageService.saveSession(_currentSession!);
      _scrollToBottom();
    }
  }

  @override
  Widget build(BuildContext context) {
    final isOnline = _apiService.isOnline;
    final currentTitle = _currentSession?.title ?? 'JARVIS AI ASSISTANT';

    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: AppTheme.background,
      drawer: _buildHistoryDrawer(),
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.menu_rounded, color: AppTheme.textPrimary),
          tooltip: 'Previous Chats',
          onPressed: () => _scaffoldKey.currentState?.openDrawer(),
        ),
        title: Row(
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: isOnline ? AppTheme.green : AppTheme.red,
                boxShadow: [
                  BoxShadow(
                    color: (isOnline ? AppTheme.green : AppTheme.red).withAlpha(160),
                    blurRadius: 6,
                    spreadRadius: 1.5,
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Flexible(
              child: GestureDetector(
                onTap: _currentSession != null
                    ? () => _showRenameDialog(_currentSession!)
                    : null,
                behavior: HitTestBehavior.opaque,
                child: Text(
                  currentTitle,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.5,
                    fontSize: 15,
                  ),
                ),
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.add_comment_outlined, color: AppTheme.primary, size: 20),
            tooltip: 'New Chat',
            onPressed: _startNewChat,
          ),
        ],
      ),
      body: _isLoadingSessions
          ? const Center(child: CircularProgressIndicator(color: AppTheme.primary))
          : Column(
              children: [
                // ── Chat conversation list ────────────────────────────────────────
                Expanded(
                  child: (_currentSession?.messages.isEmpty ?? true)
                      ? Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                Icons.auto_awesome_rounded,
                                color: AppTheme.primary.withValues(alpha: 0.35),
                                size: 40,
                              ),
                              const SizedBox(height: 12),
                              Text(
                                'Jarvis',
                                style: TextStyle(
                                  color: AppTheme.textPrimary.withValues(alpha: 0.7),
                                  fontSize: 18,
                                  fontWeight: FontWeight.w600,
                                  letterSpacing: 1.2,
                                ),
                              ),
                              const SizedBox(height: 6),
                              Text(
                                'Ask anything or give a command',
                                style: TextStyle(
                                  color: AppTheme.textSecondary.withValues(alpha: 0.5),
                                  fontSize: 13,
                                ),
                              ),
                            ],
                          ),
                        )
                      : ListView.builder(
                          controller: _scrollController,
                          padding: const EdgeInsets.all(16),
                          itemCount: _currentSession?.messages.length ?? 0,
                          itemBuilder: (ctx, i) {
                            final msg = _currentSession!.messages[i];
                            return _buildMessageBubble(msg);
                          },
                        ),
                ),

                if (_isSending) ...[
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 6),
                    child: Row(
                      children: const [
                        SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2, color: AppTheme.primary),
                        ),
                        SizedBox(width: 10),
                        Text(
                          'Jarvis is reasoning with OpenRouter & LangGraph...',
                          style: TextStyle(
                            fontSize: 11,
                            fontStyle: FontStyle.italic,
                            color: AppTheme.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],

                // ── Bottom Input Bar ───────────────────────────────────────────────
                _buildInputBar(),
              ],
            ),
    );
  }

  /// ChatGPT-style slide-out drawer showing all previous conversations
  Widget _buildHistoryDrawer() {
    final dateFormat = DateFormat('MMM d, h:mm a');

    return Drawer(
      backgroundColor: AppTheme.surface,
      child: SafeArea(
        child: Column(
          children: [
            // Drawer Header
            Container(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: AppTheme.border)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: AppTheme.primary.withAlpha(30),
                          shape: BoxShape.circle,
                        ),
                        child: const Icon(Icons.chat_bubble_outline_rounded,
                            color: AppTheme.primary, size: 20),
                      ),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: Text(
                          'Previous Chats',
                          style: TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.bold,
                            color: AppTheme.textPrimary,
                          ),
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppTheme.surfaceBright,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: AppTheme.border),
                        ),
                        child: Text(
                          '${_sessions.length}',
                          style: const TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            color: AppTheme.primary,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  // New Chat Action Button
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.primary,
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                      onPressed: _startNewChat,
                      icon: const Icon(Icons.add_rounded, size: 18),
                      label: const Text(
                        'New Chat',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13.5),
                      ),
                    ),
                  ),
                ],
              ),
            ),

            // Sessions List
            Expanded(
              child: _sessions.isEmpty
                  ? const Center(
                      child: Text(
                        'No previous chats',
                        style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                      ),
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 8),
                      itemCount: _sessions.length,
                      separatorBuilder: (ctx, i) => const SizedBox(height: 4),
                      itemBuilder: (ctx, i) {
                        final session = _sessions[i];
                        final isSelected = session.id == _currentSession?.id;
                        final lastMsg = session.messages.isNotEmpty
                            ? session.messages.last.text
                            : 'Empty chat';

                        return Container(
                          decoration: BoxDecoration(
                            color: isSelected
                                ? AppTheme.primary.withAlpha(25)
                                : AppTheme.surfaceBright.withAlpha(50),
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(
                              color: isSelected ? AppTheme.primary.withAlpha(120) : AppTheme.border,
                            ),
                          ),
                          child: ListTile(
                            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
                            leading: Icon(
                              Icons.chat_outlined,
                              size: 18,
                              color: isSelected ? AppTheme.primary : AppTheme.textSecondary,
                            ),
                            title: Text(
                              session.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: isSelected ? FontWeight.bold : FontWeight.w500,
                                color: isSelected ? Colors.white : AppTheme.textPrimary,
                              ),
                            ),
                            subtitle: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const SizedBox(height: 2),
                                Text(
                                  lastMsg,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: AppTheme.textSecondary,
                                  ),
                                ),
                                const SizedBox(height: 3),
                                Text(
                                  dateFormat.format(session.updatedAt),
                                  style: TextStyle(
                                    fontSize: 9.5,
                                    color: isSelected
                                        ? AppTheme.primary.withAlpha(180)
                                        : AppTheme.textSecondary.withAlpha(150),
                                  ),
                                ),
                              ],
                            ),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton(
                                  icon: const Icon(Icons.edit_outlined, size: 16),
                                  color: AppTheme.textSecondary,
                                  tooltip: 'Rename Chat',
                                  padding: EdgeInsets.zero,
                                  constraints: const BoxConstraints(),
                                  onPressed: () => _showRenameDialog(session),
                                ),
                                const SizedBox(width: 8),
                                IconButton(
                                  icon: const Icon(Icons.delete_outline_rounded, size: 16),
                                  color: AppTheme.red.withAlpha(200),
                                  tooltip: 'Delete Chat',
                                  padding: EdgeInsets.zero,
                                  constraints: const BoxConstraints(),
                                  onPressed: () => _confirmDeleteSession(session),
                                ),
                              ],
                            ),
                            onTap: () => _selectSession(session),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMessageBubble(ChatMessage msg) {
    final isUser = msg.isUser;
    final timeStr =
        "${msg.timestamp.hour.toString().padLeft(2, '0')}:${msg.timestamp.minute.toString().padLeft(2, '0')}";

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            Container(
              margin: const EdgeInsets.only(right: 8, top: 2),
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: AppTheme.primary.withAlpha(30),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.psychology, color: AppTheme.primary, size: 16),
            ),
          ],
          Flexible(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: isUser ? AppTheme.primary.withAlpha(40) : AppTheme.surfaceBright,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(14),
                  topRight: const Radius.circular(14),
                  bottomLeft: Radius.circular(isUser ? 14 : 2),
                  bottomRight: Radius.circular(isUser ? 2 : 14),
                ),
                border: Border.all(
                  color: isUser ? AppTheme.primary.withAlpha(120) : AppTheme.border,
                ),
              ),
              child: Column(
                crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
                children: [
                  _buildFormattedMessageText(msg.text, isUser),
                  const SizedBox(height: 4),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (!isUser && msg.durationMs != null) ...[
                        Text(
                          'Completed in ${_formatDuration(msg.durationMs!)} • ',
                          style: const TextStyle(fontSize: 9, color: AppTheme.textSecondary),
                        ),
                      ],
                      Text(
                        timeStr,
                        style: const TextStyle(fontSize: 9, color: AppTheme.textSecondary),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInputBar() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: const BoxDecoration(
        color: AppTheme.surface,
        border: Border(top: BorderSide(color: AppTheme.border)),
      ),
      child: SafeArea(
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _inputController,
                style: const TextStyle(color: AppTheme.textPrimary, fontSize: 13.5),
                decoration: InputDecoration(
                  hintText: 'Ask Jarvis, set reminder, log note...',
                  hintStyle: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                  filled: true,
                  fillColor: AppTheme.surfaceBright,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24),
                    borderSide: BorderSide.none,
                  ),
                ),
                onSubmitted: _handleSendMessage,
              ),
            ),
            const SizedBox(width: 8),
            Container(
              decoration: const BoxDecoration(
                color: AppTheme.primary,
                shape: BoxShape.circle,
              ),
              child: IconButton(
                icon: const Icon(Icons.send, color: Colors.black, size: 18),
                onPressed: _isSending ? null : () => _handleSendMessage(_inputController.text),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _formatDuration(int ms) {
    if (ms < 1000) {
      return '${(ms / 1000).toStringAsFixed(1)}s';
    } else if (ms < 60000) {
      return '${(ms / 1000).toStringAsFixed(1)}s';
    } else {
      final m = ms ~/ 60000;
      final s = ((ms % 60000) / 1000).toStringAsFixed(0);
      return '${m}m ${s}s';
    }
  }

  Widget _buildFormattedMessageText(String text, bool isUser) {
    final baseStyle = TextStyle(
      fontSize: 13,
      color: isUser ? Colors.white : AppTheme.textPrimary,
      height: 1.35,
    );

    if (!text.contains('**') && !text.contains('*') && !text.contains('`')) {
      return Text(text, style: baseStyle);
    }

    final spans = <InlineSpan>[];
    final pattern = RegExp(r'(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`)');
    int lastIndex = 0;

    for (final match in pattern.allMatches(text)) {
      if (match.start > lastIndex) {
        spans.add(TextSpan(text: text.substring(lastIndex, match.start)));
      }
      if (match.group(2) != null) {
        // **bold**
        spans.add(TextSpan(
          text: match.group(2),
          style: const TextStyle(fontWeight: FontWeight.bold),
        ));
      } else if (match.group(3) != null) {
        // *italic*
        spans.add(TextSpan(
          text: match.group(3),
          style: const TextStyle(fontStyle: FontStyle.italic),
        ));
      } else if (match.group(4) != null) {
        // `code`
        spans.add(TextSpan(
          text: match.group(4),
          style: TextStyle(
            fontFamily: 'monospace',
            backgroundColor: AppTheme.surface.withAlpha(120),
            fontSize: 12,
          ),
        ));
      }
      lastIndex = match.end;
    }

    if (lastIndex < text.length) {
      spans.add(TextSpan(text: text.substring(lastIndex)));
    }

    return RichText(
      text: TextSpan(
        style: baseStyle,
        children: spans,
      ),
    );
  }
}
