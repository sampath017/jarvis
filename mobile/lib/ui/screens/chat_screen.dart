import 'dart:async';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../models/chat_session.dart';
import '../../utils/ist_time.dart';
import '../../services/api_service.dart';
import '../../services/chat_storage_service.dart';
import '../../services/sensor_service.dart';
import '../../services/health_service.dart';
import '../../services/usage_service.dart';
import '../theme.dart';
import '../../services/command_client.dart';
import '../../services/chat_notification_service.dart';
import '../../services/sync_service.dart';
import '../../services/local_db_service.dart';
import '../widgets/chat_progress_bubble.dart';
import '../widgets/workspace_widgets.dart';
import '../widgets/action_approval_dialog.dart';
import '../../services/google_drive_service.dart';

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
  Timer? _historyRefreshTimer;
  int _historyRefreshVersion = 0;
  bool _userSelectedChat = false;
  bool _checkingRecovery = false;
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();
  final ApiService _apiService = ApiService();
  final TextEditingController _inputController = TextEditingController();
  final FocusNode _inputFocus = FocusNode();
  final ScrollController _scrollController = ScrollController();

  bool _isSending = false;
  bool _uploading = false;
  bool _cancelUpload = false;
  final List<Map<String, dynamic>> _pendingAttachments = [];
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
    LocalDbService().addListener(_onLocalHistoryChanged);
    ChatNotificationService.openThread.addListener(_openNotification);
    ChatNotificationService.updatedThread.addListener(_refreshNotification);
    ChatNotificationService.chatVisible.addListener(_updateVisibleThread);
    UsageService.openReport.addListener(_openUsageReport);
    _initChat();
  }

  Future<void> _initChat() async {
    await _loadSessions();
    if (ChatNotificationService.openThread.value != null) {
      await _reloadThread(
        ChatNotificationService.openThread.value!,
        select: true,
      );
    }
    _updateVisibleThread();
    if (UsageService.openReport.value != null) _openUsageReport();
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
    if (session == null ||
        session.messages.isEmpty ||
        !session.messages.last.isUser) {
      return;
    }
    final message = session.messages.last;
    if (DateTime.now().difference(message.timestamp).inMinutes > 20) return;
    _checkingRecovery = true;
    final snapshot = await _apiService.commandStatus(message.id);
    _checkingRecovery = false;
    if (!mounted || _isSending || snapshot == null) return;
    if (snapshot['status'] == 'complete') {
      await _reloadThread(session.id);
      return;
    }
    setState(() {
      _isSending = true;
      _activeSessionId = session.id;
      _activeRequestId = message.id;
    });
    _setProgress(CommandProgress.fromJson(snapshot));
    Future<void> poll() async {
      if (!mounted) return;
      final next = await _apiService.commandStatus(message.id);
      if (!mounted) return;
      if (next?['status'] == 'complete') {
        setState(() {
          _isSending = false;
          _activeRequestId = null;
          _activeSessionId = null;
        });
        await _reloadThread(session.id);
        return;
      }
      if (next != null) _setProgress(CommandProgress.fromJson(next));
      if (next?['calendar_action'] is Map) {
        try {
          await _apiService.handleCalendarAction(
            message.id,
            Map<String, dynamic>.from(next!['calendar_action']),
            approve: _approveAction,
          );
        } catch (_) {}
      }
      _recoveryTimer = Timer(const Duration(seconds: 3), poll);
    }

    _recoveryTimer = Timer(const Duration(seconds: 3), poll);
  }

  void _updateVisibleThread() => ChatNotificationService.setVisibleThread(
    ChatNotificationService.chatVisible.value ? _currentSession?.id : null,
  );

  Future<void> _openUsageReport() async {
    final day = UsageService.openReport.value;
    if (day == null) return;
    final text = await UsageService.savedReport(day);
    final id = 'usage_report_$day';
    final report = ChatSession(
      id: id,
      title: 'Screen time · $day',
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      messages: [
        ChatMessage(
          id: 'usage_message_$day',
          text: text,
          isUser: false,
          timestamp: DateTime.now(),
        ),
      ],
    );
    await ChatStorageService.saveSession(report);
    if (!mounted) return;
    setState(() {
      _sessions.removeWhere((s) => s.id == id);
      _sessions.insert(0, report);
      _currentSession = report;
    });
    ChatNotificationService.openThread.value = id;
    _updateVisibleThread();
  }

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
      _sessions = loaded
          .map((s) => _isSending && s.id == active?.id ? active! : s)
          .toList();
      _currentSession =
          _sessions.where((s) => s.id == selected).firstOrNull ??
          _currentSession;
    });
    _updateVisibleThread();
    _scrollToBottom();
  }

  void _onServiceUpdate() {
    if (mounted) setState(() {});
  }

  void _onLocalHistoryChanged() {
    final version = ++_historyRefreshVersion;
    _historyRefreshTimer?.cancel();
    _historyRefreshTimer = Timer(const Duration(milliseconds: 150), () async {
      final loaded = await ChatStorageService.loadSessions();
      if (!mounted || _isLoadingSessions || version != _historyRefreshVersion) {
        return;
      }
      final changed =
          loaded.length != _sessions.length ||
          loaded.any((saved) {
            final current = _sessions
                .where((s) => s.id == saved.id)
                .firstOrNull;
            if (current == null ||
                current.title != saved.title ||
                current.lastActivityAt != saved.lastActivityAt ||
                current.messages.length != saved.messages.length) {
              return true;
            }
            for (var i = 0; i < saved.messages.length; i++) {
              if (current.messages[i].id != saved.messages[i].id ||
                  current.messages[i].text != saved.messages[i].text) {
                return true;
              }
            }
            return false;
          });
      if (!changed) return;
      final active = _sessions
          .where((s) => s.id == _activeSessionId)
          .firstOrNull;
      final selected = _currentSession?.id;
      final nearBottom =
          !_scrollController.hasClients ||
          _scrollController.position.extentAfter < 120;
      setState(() {
        _sessions = loaded
            .map((s) => _isSending && s.id == active?.id ? active! : s)
            .toList();
        final restored = _sessions.where((s) => s.id == selected).firstOrNull;
        _currentSession = restored ?? _currentSession;
        if (!_userSelectedChat &&
            !_isSending &&
            _inputController.text.isEmpty &&
            (_currentSession?.messages.isEmpty ?? true)) {
          _currentSession =
              _sessions.where((s) => s.messages.isNotEmpty).firstOrNull ??
              _currentSession;
        }
      });
      _updateVisibleThread();
      if (_currentSession?.id != selected || nearBottom) _scrollToBottom();
    });
  }

  @override
  void dispose() {
    UsageService.openReport.removeListener(_openUsageReport);
    _apiService.removeListener(_onServiceUpdate);
    LocalDbService().removeListener(_onLocalHistoryChanged);
    _historyRefreshTimer?.cancel();
    ChatNotificationService.openThread.removeListener(_openNotification);
    ChatNotificationService.updatedThread.removeListener(_refreshNotification);
    ChatNotificationService.chatVisible.removeListener(_updateVisibleThread);
    ChatNotificationService.setVisibleThread(null);
    WidgetsBinding.instance.removeObserver(this);
    _recoveryTimer?.cancel();
    _inputController.dispose();
    _inputFocus.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadSessions() async {
    var loaded = await ChatStorageService.loadSessions();
    if (loaded.isEmpty) {
      await SyncService().syncNow();
      loaded = await ChatStorageService.loadSessions();
    }
    if (!mounted) return;
    if (loaded.isEmpty) {
      final initial = _createDefaultSession();
      await ChatStorageService.saveSession(initial);
      _sessions = [initial];
      _currentSession = initial;
    } else {
      _sessions = loaded;
      _currentSession =
          loaded.where((s) => s.messages.isNotEmpty).firstOrNull ??
          loaded.first;
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
    _userSelectedChat = true;
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
    _userSelectedChat = true;
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
    if (_uploading) {
      _cancelUpload = true;
      _setProgress(const CommandProgress(message: 'Pausing file upload'));
      return;
    }
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
    final query = text.trim().isEmpty && _pendingAttachments.isNotEmpty
        ? 'Keep these attachments available for this conversation.'
        : text.trim();
    final session = _currentSession;
    if (query.isEmpty || session == null || _isSending) return;
    _userSelectedChat = true;
    final historyList = session.messages
        .where((m) => !m.id.startsWith('err_') && !m.isInternalAttachmentNotice)
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
    final attachedFileIds = <String>[];
    try {
      await ChatStorageService.saveSession(session);
      if (_pendingAttachments.isNotEmpty) {
        _uploading = true;
        _cancelUpload = false;
        final selected = [..._pendingAttachments];
        for (final file in selected) {
          final memory = await GoogleDriveService.instance.save(
            file,
            query,
            saveToDrive: GoogleDriveService.requestsDriveSave(query),
            shouldContinue: () => mounted && !_cancelUpload,
            progress: (fraction) => _setProgress(
              CommandProgress(
                message:
                    'Saving ${file['name']} · ${(fraction * 100).round()}%',
                canStop: true,
              ),
            ),
          );
          if (memory['storage'] == 'drive') {
            session.messages.add(
              ChatMessage(
                text: 'Saved to My Drive: ${memory['name']}\n${memory['url']}',
                isUser: false,
                timestamp: DateTime.now(),
              ),
            );
          }
          _pendingAttachments.removeWhere((f) => f['id'] == file['id']);
          attachedFileIds.add(memory['id'].toString());
          try {
            await GoogleDriveService.instance.removeCached(file);
          } catch (_) {}
          await ChatStorageService.saveSession(session);
          if (mounted) setState(() {});
        }
        _uploading = false;
      }
      if (UsageService.isUsageQuestion(query)) {
        _setProgress(const CommandProgress(message: 'Reading your app usage'));
        response = {
          'status': 'ok',
          'message': await UsageService.answer(query),
        };
      } else if (HealthService.isHealthQuestion(query)) {
        _setProgress(
          const CommandProgress(message: 'Reading your health records'),
        );
        response = {
          'status': 'ok',
          'message': await HealthService.instance.answer(query),
        };
      } else {
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
          requestId: userMsgId,
          onProgress: _setProgress,
          approve: _approveAction,
          attachedFileIds: attachedFileIds,
        );
      }
    } catch (error) {
      response = {
        'status': 'error',
        'error': error is DriveFailure
            ? error.message
            : 'Could not finish connecting to Jarvis. Please check your connection.',
      };
    }
    _uploading = false;
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

  Future<bool> _approveAction(Map<String, dynamic> preview) async {
    if (!mounted ||
        !_isSending ||
        !ChatNotificationService.chatVisible.value ||
        WidgetsBinding.instance.lifecycleState != AppLifecycleState.resumed) {
      return false;
    }
    return showActionApproval(context, preview);
  }

  @override
  Widget build(BuildContext context) {
    final currentTitle = _currentSession?.title ?? 'New chat';
    final visibleMessages =
        _currentSession?.messages
            .where((m) => !m.isInternalAttachmentNotice)
            .toList() ??
        <ChatMessage>[];
    final showingProgress =
        _isSending && _currentSession?.id == _activeSessionId;

    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: AppTheme.background,
      drawer: _buildHistoryDrawer(),
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.menu_rounded, color: AppTheme.textPrimary),
          tooltip: 'Conversation history',
          onPressed: () => _scaffoldKey.currentState?.openDrawer(),
        ),
        title: Row(
          children: [
            const JarvisMark(),
            const SizedBox(width: 12),
            Flexible(
              child: GestureDetector(
                onTap: _currentSession != null
                    ? () => _showRenameDialog(_currentSession!)
                    : null,
                behavior: HitTestBehavior.opaque,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      (_currentSession?.messages.isEmpty ?? true)
                          ? 'Jarvis'
                          : currentTitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'Roboto',
                        fontWeight: FontWeight.w600,
                        fontSize: 17,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _apiService.isOnline
                          ? 'Personal assistant · Connected'
                          : 'Personal assistant · Offline',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'Roboto',
                        color: AppTheme.textSecondary,
                        fontSize: 11,
                        fontWeight: FontWeight.w400,
                      ),
                    ),
                  ],
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
          : WorkspaceBody(
              child: Column(
                children: [
                  // ── Chat conversation list ────────────────────────────────────────
                  Expanded(
                    child: visibleMessages.isEmpty
                        ? _buildWelcome()
                        : ListView.builder(
                            controller: _scrollController,
                            padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
                            keyboardDismissBehavior:
                                ScrollViewKeyboardDismissBehavior.onDrag,
                            itemCount:
                                visibleMessages.length +
                                (showingProgress ? 1 : 0),
                            itemBuilder: (ctx, i) {
                              if (i == visibleMessages.length) {
                                return ChatProgressBubble(
                                  key: ValueKey(_activeRequestId),
                                  progress: _progress,
                                  onStop: _progress.canStop
                                      ? _stopRequest
                                      : null,
                                );
                              }
                              final msg = visibleMessages[i];
                              return _buildMessageBubble(msg);
                            },
                          ),
                  ),

                  // ── Bottom Input Bar ───────────────────────────────────────────────
                  _buildInputBar(),
                ],
              ),
            ),
    );
  }

  Widget _buildWelcome() => LayoutBuilder(
    builder: (context, constraints) => SingleChildScrollView(
      child: ConstrainedBox(
        constraints: BoxConstraints(minHeight: constraints.maxHeight),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const JarvisMark(size: 48),
              const SizedBox(height: 24),
              Text(
                'How can I help today?',
                style: Theme.of(context).textTheme.headlineLarge,
              ),
              const SizedBox(height: 12),
              const Text(
                'Keep track of what matters, with an assistant that understands your day.',
                style: TextStyle(
                  fontSize: 15,
                  height: 1.6,
                  color: AppTheme.textSecondary,
                ),
              ),
              const SizedBox(height: 28),
              _buildSuggestion(
                Icons.alarm_outlined,
                'Set a reminder',
                'Stay on top of your next task',
                'Remind me to ',
              ),
              const SizedBox(height: 8),
              _buildSuggestion(
                Icons.route_outlined,
                'Review my activity',
                'Look back at your recent day',
                'What did I do in the last 10 minutes?',
              ),
              const SizedBox(height: 8),
              _buildSuggestion(
                Icons.note_alt_outlined,
                'Save a note',
                'Keep a thought for later',
                'Remember that ',
              ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget _buildSuggestion(
    IconData icon,
    String label,
    String description,
    String prompt,
  ) => Material(
    color: AppTheme.surface,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(AppTheme.radius),
      side: const BorderSide(color: AppTheme.border),
    ),
    clipBehavior: Clip.antiAlias,
    child: ListTile(
      leading: Icon(icon, color: AppTheme.primaryLight),
      title: Text(label),
      subtitle: Text(description),
      trailing: const Icon(Icons.arrow_forward_rounded, size: 18),
      onTap: () {
        setState(() => _inputController.text = prompt);
        _inputController.selection = TextSelection.collapsed(
          offset: prompt.length,
        );
        _inputFocus.requestFocus();
      },
    ),
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
          ..sort((a, b) => b.lastActivityAt.compareTo(a.lastActivityAt));
    String dayLabel(DateTime date) {
      final today = IstTime.display(DateTime.now());
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
                      JarvisMark(),
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
                        final label = dayLabel(
                          IstTime.display(session.lastActivityAt),
                        );
                        final showLabel =
                            index == 0 ||
                            dayLabel(
                                  IstTime.display(
                                    sessions[index - 1].lastActivityAt,
                                  ),
                                ) !=
                                label;
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
                            Padding(
                              padding: const EdgeInsets.only(bottom: 4),
                              child: Material(
                                color: selected
                                    ? AppTheme.primary.withValues(alpha: 0.13)
                                    : Colors.transparent,
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(16),
                                  side: BorderSide(
                                    color: selected
                                        ? AppTheme.primary.withValues(
                                            alpha: 0.25,
                                          )
                                        : Colors.transparent,
                                  ),
                                ),
                                clipBehavior: Clip.antiAlias,
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
                                      _isSending &&
                                              _activeSessionId == session.id
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
                                    icon: const Icon(
                                      Icons.more_horiz,
                                      size: 20,
                                    ),
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
    final timeStr = IstTime.clock(msg.timestamp);

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: isUser
            ? MainAxisAlignment.end
            : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            const Padding(
              padding: EdgeInsets.only(right: 12, top: 2),
              child: JarvisMark(size: 28),
            ),
          ],
          Flexible(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              decoration: BoxDecoration(
                color: isUser ? AppTheme.primarySurface : Colors.transparent,
                borderRadius: BorderRadius.circular(14),
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
        padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 6, 8, 8),
          decoration: BoxDecoration(
            color: AppTheme.surface,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: AppTheme.border),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_pendingAttachments.isNotEmpty)
                SizedBox(
                  height: 42,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    children: [
                      for (final file in _pendingAttachments)
                        Padding(
                          padding: const EdgeInsets.only(right: 8),
                          child: InputChip(
                            label: SizedBox(
                              width: 140,
                              child: Text(
                                file['name'].toString(),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            onDeleted: _isSending
                                ? null
                                : () async {
                                    await GoogleDriveService.instance
                                        .removeCached(file);
                                    if (mounted) {
                                      setState(
                                        () => _pendingAttachments.remove(file),
                                      );
                                    }
                                  },
                          ),
                        ),
                    ],
                  ),
                ),
              TextField(
                controller: _inputController,
                focusNode: _inputFocus,
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
                  IconButton(
                    tooltip: 'Attach PDF, image or video',
                    onPressed: _isSending ? null : _pickAttachment,
                    icon: const Icon(Icons.attach_file, size: 19),
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
                        _isSending ||
                            (_inputController.text.trim().isEmpty &&
                                _pendingAttachments.isEmpty)
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

  Future<void> _pickAttachment() async {
    try {
      if (_pendingAttachments.length >= 5) {
        throw const DriveFailure('Send up to five files at a time.');
      }
      await GoogleDriveService.instance.refresh();
      if (!GoogleDriveService.instance.connected) {
        if (!mounted) return;
        await GoogleDriveService.instance.connect();
        if (!GoogleDriveService.instance.connected || !mounted) return;
      }
      final file = await GoogleDriveService.instance.pick();
      if (file != null && mounted) {
        setState(() => _pendingAttachments.add(file));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              e is DriveFailure
                  ? e.message
                  : 'Could not attach this file. Try again.',
            ),
          ),
        );
      }
    }
  }

  Widget _buildFormattedMessageText(String text, bool isUser) {
    final baseStyle = TextStyle(
      fontSize: 15,
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
