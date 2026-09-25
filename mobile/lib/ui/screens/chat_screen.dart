import 'dart:async';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../models/chat_session.dart';
import '../../services/api_service.dart';
import '../../services/chat_storage_service.dart';
import '../../services/sensor_service.dart';
import '../../services/health_service.dart';
import '../theme.dart';
import '../../services/command_client.dart';
import '../../services/chat_notification_service.dart';
import '../../services/sync_service.dart';
import '../widgets/chat_progress_bubble.dart';

/// ChatGPT-like Conversational Agent Screen:
/// Features multi-session conversation history, rename/edit chat titles,
/// delete chats, auto-naming, and full local persistence.
class ChatScreen extends StatefulWidget {
  final SensorService sensorService;

  const ChatScreen({super.key, required this.sensorService});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with WidgetsBindingObserver {
  Timer? _recoveryTimer;
  bool _checkingRecovery = false;
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();
  final ApiService _apiService = ApiService();
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  bool _isSending = false;
  String? _activeSessionId;
  String? _activeRequestId;
  String _historyQuery = '';
  CommandProgress _progress = const CommandProgress(
    message: 'Preparing your request',
  );
  bool _isLoadingSessions = true;

  List<ChatSession> _sessions = [];
  ChatSession? _currentSession;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _apiService.addListener(_onServiceUpdate);
    ChatNotificationService.openThread.addListener(_openNotification);
    ChatNotificationService.updatedThread.addListener(_refreshNotification);
    ChatNotificationService.chatVisible.addListener(_updateVisibleThread);
    _initChat();
  }

  Future<void> _initChat() async {
    await _loadSessions();
    if (ChatNotificationService.openThread.value != null) {
      await _reloadThread(ChatNotificationService.openThread.value!, select: true);
    }
    _updateVisibleThread();
    _recoverRequest();
    // Non-blocking health check in background
    _apiService.checkHealth();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && !_isSending) {
      final id = _currentSession?.id;
      if (id != null) _reloadThread(id).then((_) => _recoverRequest());
    }
  }

  Future<void> _recoverRequest() async {
    if (_isSending || _checkingRecovery) return;
    final session = _currentSession;
    if (session == null || session.messages.isEmpty || !session.messages.last.isUser) return;
    final message = session.messages.last;
    if (DateTime.now().difference(message.timestamp).inMinutes > 20) return;
    _checkingRecovery = true;
    final snapshot = await _apiService.commandStatus(message.id);
    _checkingRecovery = false;
    if (!mounted || _isSending || snapshot == null) return;
    if (snapshot['status'] == 'complete') { await _reloadThread(session.id); return; }
    setState(() { _isSending = true; _activeSessionId = session.id; _activeRequestId = message.id; });
    _setProgress(CommandProgress.fromJson(snapshot));
    Future<void> poll() async {
      if (!mounted) return;
      final next = await _apiService.commandStatus(message.id);
      if (!mounted) return;
      if (next?['status'] == 'complete') {
        setState(() { _isSending = false; _activeRequestId = null; _activeSessionId = null; });
        await _reloadThread(session.id);
        return;
      }
      if (next != null) _setProgress(CommandProgress.fromJson(next));
      _recoveryTimer = Timer(const Duration(seconds: 3), poll);
    }
    _recoveryTimer = Timer(const Duration(seconds: 3), poll);
  }

  void _updateVisibleThread() => ChatNotificationService.setVisibleThread(
    ChatNotificationService.chatVisible.value ? _currentSession?.id : null);

  void _openNotification() {
    final id = ChatNotificationService.openThread.value;
    if (id != null) _reloadThread(id, select: true);
  }

  void _refreshNotification() {
    final id = ChatNotificationService.updatedThread.value;
    if (id != null) _reloadThread(id);
  }

  Future<void> _reloadThread(String id, {bool select = false}) async {
    await SyncService().syncNow();
    final loaded = await ChatStorageService.loadSessions();
    if (!mounted) return;
    // The streaming request retains its original session object until completion.
    final active = _sessions.where((s) => s.id == _activeSessionId).firstOrNull;
    final selected = select ? id : _currentSession?.id;
    setState(() {
      _sessions = loaded.map((s) => _isSending && s.id == active?.id ? active! : s).toList();
      _currentSession = _sessions.where((s) => s.id == selected).firstOrNull ?? _currentSession;
    });
    _updateVisibleThread();
    _scrollToBottom();
  }

  void _onServiceUpdate() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _apiService.removeListener(_onServiceUpdate);
    ChatNotificationService.openThread.removeListener(_openNotification);
    ChatNotificationService.updatedThread.removeListener(_refreshNotification);
    ChatNotificationService.chatVisible.removeListener(_updateVisibleThread);
    ChatNotificationService.setVisibleThread(null);
    WidgetsBinding.instance.removeObserver(this);
    _recoveryTimer?.cancel();
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

    _updateVisibleThread();
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
    _updateVisibleThread();
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
                hintStyle: const TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 13,
                ),
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
              validator: (v) => (v == null || v.trim().isEmpty)
                  ? 'Title cannot be empty'
                  : null,
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text(
                'Cancel',
                style: TextStyle(color: AppTheme.textSecondary),
              ),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.primary,
                foregroundColor: Colors.black,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
              onPressed: () {
                if (formKey.currentState?.validate() ?? false) {
                  Navigator.of(ctx).pop(controller.text.trim());
                }
              },
              child: const Text(
                'Save',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
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
    if (_isSending && session.id == _activeSessionId) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Stop the active request before deleting this chat.'),
        ),
      );
      return;
    }
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
            style: const TextStyle(
              color: AppTheme.textSecondary,
              fontSize: 13,
              height: 1.4,
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text(
                'Cancel',
                style: TextStyle(color: AppTheme.textSecondary),
              ),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.red,
                foregroundColor: AppTheme.background,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text(
                'Delete',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
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

  void _setProgress(CommandProgress progress) {
    if (!mounted) return;
    final followBottom =
        !_scrollController.hasClients ||
        _scrollController.position.extentAfter < 140;
    setState(() => _progress = progress);
    if (followBottom) _scrollToBottom();
  }

  Future<void> _stopRequest() async {
    final id = _activeRequestId;
    if (id == null) return;
    final stopped = await _apiService.cancelCommand(id);
    if (!mounted || !_isSending) return;
    if (stopped) {
      _setProgress(
        CommandProgress(
          message: 'Stopping after the current operation',
          steps: _progress.steps,
          elapsedSeconds: _progress.elapsedSeconds,
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Could not reach Jarvis to stop it. The request may still be running.',
          ),
        ),
      );
    }
  }

  Future<void> _handleSendMessage(String text) async {
    final query = text.trim();
    final session = _currentSession;
    if (query.isEmpty || session == null || _isSending) return;
    final historyList = session.messages
        .where((m) => !m.id.startsWith('err_'))
        .toList()
        .reversed
        .take(8)
        .toList()
        .reversed
        .map(
          (m) => <String, dynamic>{
            'role': m.isUser ? 'user' : 'assistant',
            'content': m.text,
          },
        )
        .toList();
    final userMsgId = 'msg_${DateTime.now().microsecondsSinceEpoch}';
    _inputController.clear();
    if (session.title == 'New Chat') {
      session.title = query.length > 28
          ? '${query.substring(0, 28).trim()}…'
          : query;
    }
    setState(() {
      session.messages.add(
        ChatMessage(
          id: userMsgId,
          text: query,
          isUser: true,
          timestamp: DateTime.now(),
        ),
      );
      session.updatedAt = DateTime.now();
      _isSending = true;
      _activeSessionId = session.id;
      _activeRequestId = userMsgId;
      _progress = const CommandProgress(message: 'Preparing your request');
    });
    _scrollToBottom();
    final watch = Stopwatch()..start();
    Map<String, dynamic>? response;
    try {
      await ChatStorageService.saveSession(session);
      if (HealthService.isHealthQuestion(query)) {
        _setProgress(
          const CommandProgress(message: 'Reading your health records'),
        );
        response = {
          'status': 'ok',
          'message': await HealthService.instance.answer(query),
        };
      } else {
        _setProgress(
          const CommandProgress(message: 'Checking your current location'),
        );
        Map<String, dynamic>? coords;
        try {
          coords = await widget.sensorService.getCurrentLocation(
            requestIfNeeded: true,
          );
        } catch (_) {
          /* Context is optional; keep processing when unavailable. */
        }
        _setProgress(
          const CommandProgress(
            message: 'Connecting to Jarvis',
            steps: ['Prepared your request'],
          ),
        );
        response = await _apiService.sendCommand(
          query,
          threadId: session.id,
          history: historyList,
          latitude: (coords?['latitude'] as num?)?.toDouble(),
          longitude: (coords?['longitude'] as num?)?.toDouble(),
          requestId: userMsgId,
          onProgress: _setProgress,
        );
      }
    } catch (_) {
      response = {
        'status': 'error',
        'error':
            'Could not finish connecting to Jarvis. Please check your connection.',
      };
    }
    watch.stop();
    final succeeded = response?['status'] == 'ok';
    session.messages.add(
      ChatMessage(
        id: succeeded ? (response?['run_id']?.toString()) : 'err_$userMsgId',
        text: succeeded
            ? (response?['message']?.toString() ?? 'Done.')
            : (response?['error']?.toString() ??
                  'The request could not finish.'),
        isUser: false,
        timestamp: DateTime.now(),
        runId: response?['run_id']?.toString(),
        executedRecords: List<String>.from(response?['changed_records'] ?? []),
        durationMs: watch.elapsedMilliseconds,
      ),
    );
    session.updatedAt = DateTime.now();
    // Persist into the original chat even if the user opened a different one.
    if (mounted) {
      setState(() {
        _isSending = false;
        _activeSessionId = null;
        _activeRequestId = null;
      });
      if (_currentSession?.id == session.id) _scrollToBottom();
    }
    await ChatStorageService.saveSession(session);
  }

  @override
  Widget build(BuildContext context) {
    final currentTitle = _currentSession?.title ?? 'New chat';
    final showingProgress =
        _isSending && _currentSession?.id == _activeSessionId;

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
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                color: AppTheme.primary.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(11),
              ),
              child: const Icon(
                Icons.auto_awesome_rounded,
                size: 18,
                color: AppTheme.primary,
              ),
            ),
            const SizedBox(width: 12),
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
                    fontWeight: FontWeight.w600,
                    fontSize: 20,
                  ),
                ),
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(
              Icons.edit_outlined,
              color: AppTheme.textPrimary,
              size: 21,
            ),
            tooltip: 'New Chat',
            onPressed: _startNewChat,
          ),
        ],
      ),
      body: _isLoadingSessions
          ? const Center(
              child: CircularProgressIndicator(color: AppTheme.primary),
            )
          : Column(
              children: [
                // ── Chat conversation list ────────────────────────────────────────
                Expanded(
                  child: (_currentSession?.messages.isEmpty ?? true)
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 24),
                            child: Container(
                              width: double.infinity,
                              padding: const EdgeInsets.all(24),
                              decoration: BoxDecoration(
                                color: AppTheme.surface,
                                borderRadius: BorderRadius.circular(24),
                                border: Border.all(
                                  color: AppTheme.border.withValues(
                                    alpha: 0.55,
                                  ),
                                ),
                              ),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Container(
                                    padding: const EdgeInsets.all(12),
                                    decoration: BoxDecoration(
                                      color: AppTheme.primary.withValues(
                                        alpha: 0.16,
                                      ),
                                      borderRadius: BorderRadius.circular(16),
                                    ),
                                    child: const Icon(
                                      Icons.auto_awesome_rounded,
                                      color: AppTheme.primary,
                                      size: 24,
                                    ),
                                  ),
                                  const SizedBox(height: 20),
                                  const Text(
                                    'Jarvis is ready',
                                    style: TextStyle(
                                      color: AppTheme.textPrimary,
                                      fontSize: 22,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  const SizedBox(height: 8),
                                  const Text(
                                    'Ask about your day, set a reminder, or keep a note.',
                                    style: TextStyle(
                                      color: AppTheme.textSecondary,
                                      fontSize: 14,
                                      height: 1.4,
                                    ),
                                  ),
                                  const SizedBox(height: 18),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 8,
                                    children: [
                                      _buildSuggestion(
                                        'Set a reminder',
                                        'Remind me to ',
                                      ),
                                      _buildSuggestion(
                                        'My recent activity',
                                        'What did I do in the last 10 minutes?',
                                      ),
                                      _buildSuggestion(
                                        'Save a note',
                                        'Remember that ',
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                          ),
                        )
                      : ListView.builder(
                          controller: _scrollController,
                          padding: const EdgeInsets.fromLTRB(14, 18, 14, 18),
                          itemCount:
                              (_currentSession?.messages.length ?? 0) +
                              (showingProgress ? 1 : 0),
                          itemBuilder: (ctx, i) {
                            if (i == _currentSession!.messages.length) {
                              return ChatProgressBubble(
                                key: ValueKey(_activeRequestId),
                                progress: _progress,
                                onStop: _progress.canStop ? _stopRequest : null,
                              );
                            }
                            final msg = _currentSession!.messages[i];
                            return _buildMessageBubble(msg);
                          },
                        ),
                ),

                // ── Bottom Input Bar ───────────────────────────────────────────────
                _buildInputBar(),
              ],
            ),
    );
  }

  Widget _buildSuggestion(String label, String prompt) => ActionChip(
    label: Text(label),
    labelStyle: const TextStyle(color: AppTheme.textPrimary, fontSize: 12),
    backgroundColor: AppTheme.surfaceBright,
    side: const BorderSide(color: AppTheme.border),
    onPressed: () {
      _inputController.text = prompt;
      _inputController.selection = TextSelection.collapsed(
        offset: prompt.length,
      );
    },
  );

  Widget _buildHistoryDrawer() {
    final sessions =
        _sessions
            .where(
              (session) =>
                  session.title.toLowerCase().contains(
                    _historyQuery.toLowerCase(),
                  ) ||
                  session.messages.any(
                    (m) => m.text.toLowerCase().contains(
                      _historyQuery.toLowerCase(),
                    ),
                  ),
            )
            .toList()
          ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    String dayLabel(DateTime date) {
      final today = DateTime.now();
      final days = DateTime(
        today.year,
        today.month,
        today.day,
      ).difference(DateTime(date.year, date.month, date.day)).inDays;
      return days == 0
          ? 'Today'
          : days == 1
          ? 'Yesterday'
          : DateFormat('MMMM d').format(date);
    }

    return Drawer(
      backgroundColor: AppTheme.background,
      child: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(
                        Icons.auto_awesome_rounded,
                        color: AppTheme.primary,
                        size: 25,
                      ),
                      SizedBox(width: 12),
                      Text(
                        'Your chats',
                        style: TextStyle(
                          fontSize: 23,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Pick up where you left off',
                    style: TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 13,
                    ),
                  ),
                  const SizedBox(height: 22),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _startNewChat,
                      icon: const Icon(Icons.add_rounded),
                      label: const Text('New conversation'),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    onChanged: (value) => setState(() => _historyQuery = value),
                    decoration: InputDecoration(
                      hintText: 'Search conversations',
                      prefixIcon: const Icon(Icons.search_rounded, size: 20),
                      filled: true,
                      fillColor: AppTheme.surface,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(16),
                        borderSide: BorderSide.none,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: sessions.isEmpty
                  ? const Center(
                      child: Text(
                        'No conversations found',
                        style: TextStyle(color: AppTheme.textSecondary),
                      ),
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
                      itemCount: sessions.length,
                      itemBuilder: (context, index) {
                        final session = sessions[index];
                        final selected = session.id == _currentSession?.id;
                        final label = dayLabel(session.updatedAt);
                        final showLabel =
                            index == 0 ||
                            dayLabel(sessions[index - 1].updatedAt) != label;
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (showLabel)
                              Padding(
                                padding: const EdgeInsets.fromLTRB(
                                  12,
                                  16,
                                  12,
                                  8,
                                ),
                                child: Text(
                                  label,
                                  style: const TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                    color: AppTheme.textSecondary,
                                  ),
                                ),
                              ),
                            Container(
                              margin: const EdgeInsets.only(bottom: 4),
                              decoration: BoxDecoration(
                                color: selected
                                    ? AppTheme.primary.withValues(alpha: 0.13)
                                    : Colors.transparent,
                                borderRadius: BorderRadius.circular(16),
                                border: Border.all(
                                  color: selected
                                      ? AppTheme.primary.withValues(alpha: 0.25)
                                      : Colors.transparent,
                                ),
                              ),
                              child: ListTile(
                                contentPadding: const EdgeInsets.only(
                                  left: 12,
                                  right: 2,
                                ),
                                title: Text(
                                  session.title,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    fontSize: 14,
                                    fontWeight: selected
                                        ? FontWeight.w600
                                        : FontWeight.w400,
                                  ),
                                ),
                                subtitle: Padding(
                                  padding: const EdgeInsets.only(top: 4),
                                  child: Text(
                                    _isSending && _activeSessionId == session.id
                                        ? 'Jarvis is working on this request'
                                        : session.messages.isEmpty
                                        ? 'Start a conversation'
                                        : session.messages.last.text,
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontSize: 12,
                                      height: 1.4,
                                      color: AppTheme.textSecondary,
                                    ),
                                  ),
                                ),
                                trailing: PopupMenuButton<String>(
                                  tooltip: 'Chat options',
                                  icon: const Icon(Icons.more_horiz, size: 20),
                                  onSelected: (value) {
                                    if (value == 'rename') {
                                      _showRenameDialog(session);
                                    } else {
                                      _confirmDeleteSession(session);
                                    }
                                  },
                                  itemBuilder: (_) => const [
                                    PopupMenuItem(
                                      value: 'rename',
                                      child: Text('Rename'),
                                    ),
                                    PopupMenuItem(
                                      value: 'delete',
                                      child: Text('Delete'),
                                    ),
                                  ],
                                ),
                                onTap: () => _selectSession(session),
                              ),
                            ),
                          ],
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
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: isUser
            ? MainAxisAlignment.end
            : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            Container(
              margin: const EdgeInsets.only(right: 10, top: 2),
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                color: AppTheme.primary.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(11),
              ),
              child: const Icon(
                Icons.auto_awesome_rounded,
                color: AppTheme.primary,
                size: 18,
              ),
            ),
          ],
          Flexible(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              decoration: BoxDecoration(
                color: isUser
                    ? AppTheme.primary.withValues(alpha: 0.19)
                    : AppTheme.surface,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(20),
                  topRight: const Radius.circular(20),
                  bottomLeft: Radius.circular(isUser ? 20 : 5),
                  bottomRight: Radius.circular(isUser ? 5 : 20),
                ),
                border: Border.all(
                  color: isUser
                      ? AppTheme.primary.withValues(alpha: 0.25)
                      : AppTheme.border.withValues(alpha: 0.55),
                ),
              ),
              child: Column(
                crossAxisAlignment: isUser
                    ? CrossAxisAlignment.end
                    : CrossAxisAlignment.start,
                children: [
                  _buildFormattedMessageText(msg.text, isUser),
                  const SizedBox(height: 4),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        timeStr,
                        style: TextStyle(
                          fontSize: 10,
                          color: isUser
                              ? Colors.white70
                              : AppTheme.textSecondary,
                        ),
                      ),
                      if (!isUser && msg.durationMs != null) ...[
                        const SizedBox(width: 8),
                        const Icon(
                          Icons.timer_outlined,
                          size: 12,
                          color: AppTheme.textSecondary,
                        ),
                        const SizedBox(width: 3),
                        Text(
                          _formatReplyDuration(msg.durationMs!),
                          style: const TextStyle(
                            fontSize: 10,
                            color: AppTheme.textSecondary,
                          ),
                        ),
                      ],
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

  String _formatReplyDuration(int milliseconds) {
    final seconds = milliseconds / 1000;
    if (seconds < 10) return '${seconds.toStringAsFixed(1)}s';
    final roundedSeconds = seconds.round();
    if (roundedSeconds < 60) return '${roundedSeconds}s';
    final minutes = roundedSeconds ~/ 60;
    final remainingSeconds = roundedSeconds % 60;
    return remainingSeconds == 0
        ? '${minutes}m'
        : '${minutes}m ${remainingSeconds}s';
  }

  Widget _buildInputBar() {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 6, 12, 12),
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 6, 8, 8),
          decoration: BoxDecoration(
            color: AppTheme.surface,
            borderRadius: BorderRadius.circular(26),
            border: Border.all(color: AppTheme.border.withValues(alpha: 0.7)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _inputController,
                minLines: 1,
                maxLines: 5,
                textCapitalization: TextCapitalization.sentences,
                keyboardType: TextInputType.multiline,
                textInputAction: TextInputAction.newline,
                onChanged: (_) => setState(() {}),
                style: const TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 15,
                  height: 1.5,
                ),
                decoration: const InputDecoration(
                  hintText: 'Message Jarvis…',
                  filled: false,
                  hintStyle: TextStyle(color: AppTheme.textSecondary),
                  border: InputBorder.none,
                  enabledBorder: InputBorder.none,
                  focusedBorder: InputBorder.none,
                  contentPadding: EdgeInsets.symmetric(vertical: 12),
                ),
              ),
              Row(
                children: [
                  const Icon(
                    Icons.auto_awesome_outlined,
                    size: 16,
                    color: AppTheme.textSecondary,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _isSending
                          ? 'You can keep writing while Jarvis works'
                          : 'Ask, plan, or remember something',
                      style: const TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: 11,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    tooltip: 'Send message',
                    onPressed:
                        _isSending || _inputController.text.trim().isEmpty
                        ? null
                        : () => _handleSendMessage(_inputController.text),
                    icon: const Icon(Icons.arrow_upward_rounded, size: 21),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildFormattedMessageText(String text, bool isUser) {
    final baseStyle = TextStyle(
      fontSize: 14,
      color: isUser ? Colors.white : AppTheme.textPrimary,
      height: 1.45,
    );

    if (!text.contains('**') && !text.contains('*') && !text.contains('`')) {
      return SelectableText(text, style: baseStyle);
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
        spans.add(
          TextSpan(
            text: match.group(2),
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        );
      } else if (match.group(3) != null) {
        // *italic*
        spans.add(
          TextSpan(
            text: match.group(3),
            style: const TextStyle(fontStyle: FontStyle.italic),
          ),
        );
      } else if (match.group(4) != null) {
        // `code`
        spans.add(
          TextSpan(
            text: match.group(4),
            style: TextStyle(
              fontFamily: 'monospace',
              backgroundColor: AppTheme.surface.withAlpha(120),
              fontSize: 12,
            ),
          ),
        );
      }
      lastIndex = match.end;
    }

    if (lastIndex < text.length) {
      spans.add(TextSpan(text: text.substring(lastIndex)));
    }

    return RichText(
      text: TextSpan(style: baseStyle, children: spans),
    );
  }
}
