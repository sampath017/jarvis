import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../models/chat_session.dart';
import '../../utils/ist_time.dart';
import '../../services/api_service.dart';
import '../../services/chat_storage_service.dart';
import '../../services/local_chat_archive_service.dart';
import '../../services/sensor_service.dart';
import '../../services/usage_service.dart';
import '../theme.dart';
import '../../services/command_client.dart';
import '../../services/chat_notification_service.dart';
import '../../services/sync_service.dart';
import '../../services/local_db_service.dart';
import '../widgets/chat_progress_bubble.dart';
import '../widgets/workspace_widgets.dart';
import '../widgets/action_approval_dialog.dart';
import '../widgets/chat_history_list.dart';
import '../widgets/chat_archive_confirmation.dart';
import '../widgets/chat_welcome.dart';
import '../widgets/chat_message_content.dart';
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
  Timer? _historySearchTimer;
  Set<String>? _historyMatches;
  int _selectionVersion = 0;
  Future<void>? _selectionTask;
  bool _loadingOlder = false;
  int _historyRefreshVersion = 0;
  bool _userSelectedChat = false;
  bool _checkingRecovery = false;
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();
  final ApiService _apiService = ApiService();
  final TextEditingController _inputController = TextEditingController();
  final TextEditingController _historyController = TextEditingController();
  final FocusNode _inputFocus = FocusNode();
  final ScrollController _scrollController = ScrollController();
  bool _scrollScheduled = false;
  bool _historyVisible = true;
  late bool _lastOnline;

  bool _isSending = false;
  String? _restoringHistoryId;
  String? _archivingSessionId;
  Completer<void>? _restoreCompletion;
  bool _uploading = false;
  bool _cancelUpload = false;
  final List<Map<String, dynamic>> _pendingAttachments = [];
  String? _activeSessionId;
  String? _activeRequestId;
  String _historyQuery = '';
  final _progress = ValueNotifier<CommandProgress>(
    const CommandProgress(message: 'Preparing your request'),
  );
  bool _isLoadingSessions = true;

  List<ChatSession> _sessions = [];
  ChatSession? _currentSession;
  String? _sessionLoadError;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _lastOnline = _apiService.isOnline;
    _apiService.addListener(_onServiceUpdate);
    LocalDbService().addListener(_onLocalHistoryChanged);
    ChatNotificationService.openThread.addListener(_openNotification);
    ChatNotificationService.updatedThread.addListener(_refreshNotification);
    ChatNotificationService.chatVisible.addListener(_onChatVisibilityChanged);
    UsageService.openReport.addListener(_openUsageReport);
    _initChat();
  }

  Future<void> _initChat() async {
    try {
      await _loadSessions();
    } catch (_) {
      if (mounted) {
        setState(
          () => _sessionLoadError = 'Could not load chats. Please retry.',
        );
      }
      return;
    }
    if (!mounted) return;
    final selected = _currentSession?.id;
    if (selected != null) await _restoreArchivedHistory(selected);
    if (ChatNotificationService.openThread.value != null) {
      await _reloadThread(
        ChatNotificationService.openThread.value!,
        select: true,
        recordUse: true,
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
      if (id != null) {
        _reloadThread(id, recordUse: true).then((_) => _recoverRequest());
      }
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

  void _recordChatUse({String? threadId}) {
    final id = threadId ?? _currentSession?.id;
    if (id != null && ChatNotificationService.chatVisible.value) {}
  }

  void _onChatVisibilityChanged() {
    _updateVisibleThread();
    _recordChatUse();
  }

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
    if (id != null) _reloadThread(id, select: true, recordUse: true);
  }

  void _refreshNotification() {
    final id = ChatNotificationService.updatedThread.value;
    if (id != null) _reloadThread(id);
  }

  Future<void> _restoreArchivedHistory(String id) async {
    if (!mounted || _isSending) return;
    final inFlight = _restoreCompletion;
    if (inFlight != null) {
      await inFlight.future;
      if (mounted) await _restoreArchivedHistory(id);
      return;
    }
    final backup = LocalChatArchiveService();
    if (!await backup.needsRestore(id) || !mounted) return;
    // The SQLite lookup above yields; recheck in case another selection won.
    if (_restoreCompletion != null) return _restoreArchivedHistory(id);
    final completion = Completer<void>();
    _restoreCompletion = completion;
    setState(() => _restoringHistoryId = id);
    try {
      await backup.restoreHistory(id);
      final loaded = await _loadVisibleSessions();
      if (mounted) {
        setState(() {
          _sessions = loaded;
          _currentSession =
              loaded.where((s) => s.id == _currentSession?.id).firstOrNull ??
              _currentSession;
        });
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Older history could not be restored. Reconnect cloud Google access and reopen this chat.',
            ),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _restoringHistoryId = null);
      _restoreCompletion = null;
      completion.complete();
    }
  }

  Future<List<ChatSession>> _loadVisibleSessions({String? selectedId}) {
    final length = _currentSession?.messages.length ?? 0;
    return ChatStorageService.loadSessions(
      summariesOnly: true,
      loadThreadId: selectedId ?? _currentSession?.id,
      messageLimit: length < 60 ? 60 : length,
    );
  }

  Future<void> _reloadThread(
    String id, {
    bool select = false,
    bool sync = true,
    bool recordUse = false,
  }) async {
    final version = select ? ++_selectionVersion : _selectionVersion;
    if (recordUse) _recordChatUse(threadId: id);
    if (sync) await SyncService().syncNow();
    await _restoreArchivedHistory(id);
    final loaded = await _loadVisibleSessions(
      selectedId: select ? id : _currentSession?.id,
    );
    if (!mounted || version != _selectionVersion) return;
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
    if (mounted && _lastOnline != _apiService.isOnline) {
      setState(() => _lastOnline = _apiService.isOnline);
      if (_apiService.isOnline) _recordChatUse();
    }
  }

  void _onLocalHistoryChanged() {
    final version = ++_historyRefreshVersion;
    _historyRefreshTimer?.cancel();
    _historyRefreshTimer = Timer(const Duration(milliseconds: 150), () async {
      final selectionVersion = _selectionVersion;
      final loaded = await _loadVisibleSessions();
      if (!mounted ||
          _isLoadingSessions ||
          version != _historyRefreshVersion ||
          selectionVersion != _selectionVersion) {
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
                current.messageCount != saved.messageCount ||
                current.isArchived != saved.isArchived ||
                current.hasArchive != saved.hasArchive ||
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
              _sessions.where((s) => s.hasMessages).firstOrNull ??
              _currentSession;
        }
      });
      _updateVisibleThread();
      if (_currentSession?.id != selected && _currentSession != null) {
        _selectionTask = _reloadThread(
          _currentSession!.id,
          select: true,
          sync: false,
          recordUse: true,
        );
      }
      if (_currentSession?.id != selected || nearBottom) _scrollToBottom();
    });
  }

  @override
  void dispose() {
    UsageService.openReport.removeListener(_openUsageReport);
    _apiService.removeListener(_onServiceUpdate);
    LocalDbService().removeListener(_onLocalHistoryChanged);
    _historyRefreshTimer?.cancel();
    _historySearchTimer?.cancel();
    ChatNotificationService.openThread.removeListener(_openNotification);
    ChatNotificationService.updatedThread.removeListener(_refreshNotification);
    ChatNotificationService.chatVisible.removeListener(
      _onChatVisibilityChanged,
    );
    ChatNotificationService.setVisibleThread(null);
    WidgetsBinding.instance.removeObserver(this);
    _recoveryTimer?.cancel();
    _inputController.dispose();
    _historyController.dispose();
    _inputFocus.dispose();
    _scrollController.dispose();
    _progress.dispose();
    super.dispose();
  }

  Future<void> _loadSessions() async {
    var loaded = await _loadVisibleSessions();
    if (loaded.isEmpty) {
      await SyncService().syncNow();
      loaded = await _loadVisibleSessions();
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
          loaded.where((s) => s.hasMessages).firstOrNull ?? loaded.first;
      final chosen = await ChatStorageService.loadSession(
        _currentSession!.id,
        messageLimit: 60,
      );
      if (!mounted) return;
      if (chosen != null) {
        _currentSession = chosen;
        _sessions = _sessions
            .map((s) => s.id == chosen.id ? chosen : s)
            .toList();
      }
    }
    if (mounted) {
      setState(() {
        _isLoadingSessions = false;
      });
      _scrollToBottom();
      _recordChatUse();
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
    ++_selectionVersion;
    _selectionTask = null;
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
    _selectionTask = _reloadThread(
      session.id,
      select: true,
      sync: false,
      recordUse: true,
    );
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
                foregroundColor: AppTheme.background,
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
    if (_scrollScheduled) return;
    _scrollScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _scrollScheduled = false;
      if (mounted && _scrollController.hasClients) {
        if (_scrollController.position.extentAfter < 1) return;
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 160),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _setProgress(CommandProgress progress) {
    if (!mounted) return;
    final previous = _progress.value;
    final contentChanged =
        previous.message != progress.message ||
        !listEquals(previous.steps, progress.steps);
    if (!contentChanged &&
        previous.elapsedSeconds == progress.elapsedSeconds &&
        previous.canStop == progress.canStop) {
      return;
    }
    final followBottom =
        !_scrollController.hasClients ||
        _scrollController.position.extentAfter < 140;
    _progress.value = progress;
    if (contentChanged && followBottom) _scrollToBottom();
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
          steps: _progress.value.steps,
          elapsedSeconds: _progress.value.elapsedSeconds,
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
    final selectedId = _currentSession?.id;
    await _selectionTask;
    if (!mounted || _currentSession?.id != selectedId) return;
    final query = text.trim().isEmpty && _pendingAttachments.isNotEmpty
        ? 'Keep these attachments available for this conversation.'
        : text.trim();
    final selectedSession = _currentSession;
    if (query.isEmpty ||
        selectedSession == null ||
        _isSending ||
        _archivingSessionId == selectedSession.id ||
        _restoringHistoryId != null) {
      return;
    }
    if (await LocalChatArchiveService().needsRestore(selectedSession.id)) {
      await _restoreArchivedHistory(selectedSession.id);
      if (!mounted ||
          await LocalChatArchiveService().needsRestore(selectedSession.id)) {
        return;
      }
    }
    final session = _currentSession;
    if (session == null || session.id != selectedSession.id || _isSending) {
      return;
    }
    _recordChatUse();
    _userSelectedChat = true;
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
      session.isArchived = false;
      _isSending = true;
      _activeSessionId = session.id;
      _activeRequestId = userMsgId;
      _progress.value = const CommandProgress(
        message: 'Preparing your request',
      );
    });
    _scrollToBottom();
    final watch = Stopwatch()..start();
    Map<String, dynamic>? response;
    final attachedFileIds = <String>[];
    try {
      await ChatStorageService.saveSession(session);
      final historyList = await ChatStorageService.loadCommandHistory(
        session,
        currentMessageId: userMsgId,
      );
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
    } catch (error) {
      response = {
        'status': 'error',
        'error': error is DriveFailure
            ? error.message
            : error is ChatHistoryReadException
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
    final visible = _currentSession?.id;
    if (mounted && visible != null && visible != session.id) {
      unawaited(_restoreArchivedHistory(visible));
    }
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
    final hasOlder =
        (_currentSession?.messageCount ?? 0) >
        (_currentSession?.messages.length ?? 0);

    return LayoutBuilder(
      builder: (context, constraints) {
        final dockHistory = constraints.maxWidth >= 980;
        return Row(
          children: [
            if (dockHistory && _historyVisible) ...[
              SizedBox(width: 264, child: _buildHistoryPanel()),
              const VerticalDivider(width: 1),
            ],
            Expanded(
              child: Scaffold(
                key: _scaffoldKey,
                backgroundColor: AppTheme.background,
                drawer: dockHistory
                    ? null
                    : Drawer(
                        backgroundColor: AppTheme.sidebar,
                        child: _buildHistoryPanel(),
                      ),
                appBar: AppBar(
                  titleSpacing: 4,
                  shape: const Border(
                    bottom: BorderSide(color: AppTheme.border, width: 0.5),
                  ),
                  leading: IconButton(
                    icon: const Icon(Icons.view_sidebar_outlined, size: 21),
                    tooltip: 'Conversation history',
                    onPressed: () {
                      if (dockHistory) {
                        setState(() => _historyVisible = !_historyVisible);
                      } else {
                        _scaffoldKey.currentState?.openDrawer();
                      }
                    },
                  ),
                  title: Row(
                    children: [
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
                              Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Container(
                                    width: 5,
                                    height: 5,
                                    decoration: BoxDecoration(
                                      shape: BoxShape.circle,
                                      color: _apiService.isOnline
                                          ? AppTheme.green
                                          : AppTheme.amber,
                                    ),
                                  ),
                                  const SizedBox(width: 6),
                                  Text(
                                    _apiService.isOnline
                                        ? 'Connected'
                                        : 'Offline',
                                    style: const TextStyle(
                                      color: AppTheme.textSecondary,
                                      fontSize: 11,
                                      fontWeight: FontWeight.w400,
                                    ),
                                  ),
                                ],
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
                      onPressed: _isLoadingSessions ? null : _startNewChat,
                    ),
                  ],
                ),
                body: _isLoadingSessions
                    ? Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (_sessionLoadError == null)
                              const CircularProgressIndicator(
                                color: AppTheme.primary,
                              ),
                            const SizedBox(height: 16),
                            Text(_sessionLoadError ?? 'Loading recent chats…'),
                            if (_sessionLoadError != null)
                              TextButton(
                                onPressed: () {
                                  setState(() => _sessionLoadError = null);
                                  _initChat();
                                },
                                child: const Text('Retry'),
                              ),
                          ],
                        ),
                      )
                    : WorkspaceBody(
                        child: Column(
                          children: [
                            if (_currentSession?.isArchived ?? false)
                              Container(
                                width: double.infinity,
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 16,
                                  vertical: 10,
                                ),
                                color: AppTheme.amber.withValues(alpha: 0.1),
                                child: const Row(
                                  children: [
                                    Icon(
                                      Icons.archive_outlined,
                                      size: 18,
                                      color: AppTheme.amber,
                                    ),
                                    SizedBox(width: 10),
                                    Expanded(
                                      child: Text(
                                        'Archived on this phone. Send a message to continue.',
                                        style: TextStyle(
                                          fontSize: 12,
                                          color: AppTheme.amber,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            // ── Chat conversation list ────────────────────────────────────────
                            Expanded(
                              child:
                                  visibleMessages.isEmpty &&
                                      (_currentSession?.hasMessages ?? false)
                                  ? Center(
                                      child: _restoringHistoryId != null
                                          ? const CircularProgressIndicator()
                                          : TextButton(
                                              onPressed: () => _reloadThread(
                                                _currentSession!.id,
                                                sync: false,
                                              ),
                                              child: const Text(
                                                'Load saved conversation history',
                                              ),
                                            ),
                                    )
                                  : visibleMessages.isEmpty
                                  ? _buildWelcome()
                                  : ListView.builder(
                                      controller: _scrollController,
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 20,
                                        vertical: 24,
                                      ),
                                      keyboardDismissBehavior:
                                          ScrollViewKeyboardDismissBehavior
                                              .onDrag,
                                      itemCount:
                                          visibleMessages.length +
                                          (showingProgress ? 1 : 0) +
                                          (hasOlder ? 1 : 0),
                                      itemBuilder: (ctx, i) {
                                        if (hasOlder && i == 0) {
                                          return TextButton.icon(
                                            onPressed: _loadingOlder
                                                ? null
                                                : _loadOlderMessages,
                                            icon: const Icon(
                                              Icons.history_rounded,
                                            ),
                                            label: Text(
                                              _loadingOlder
                                                  ? 'Loading older messages…'
                                                  : 'Load older messages',
                                            ),
                                          );
                                        }
                                        final messageIndex =
                                            i - (hasOlder ? 1 : 0);
                                        if (messageIndex ==
                                            visibleMessages.length) {
                                          return ValueListenableBuilder<
                                            CommandProgress
                                          >(
                                            valueListenable: _progress,
                                            builder:
                                                (context, progress, child) =>
                                                    ChatProgressBubble(
                                                      key: ValueKey(
                                                        _activeRequestId,
                                                      ),
                                                      progress: progress,
                                                      onStop: progress.canStop
                                                          ? _stopRequest
                                                          : null,
                                                    ),
                                          );
                                        }
                                        final msg =
                                            visibleMessages[messageIndex];
                                        return _buildMessageBubble(msg);
                                      },
                                    ),
                            ),

                            // ── Bottom Input Bar ───────────────────────────────────────────────
                            _buildInputBar(),
                          ],
                        ),
                      ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildWelcome() => ChatWelcome(
    onPrompt: (prompt) {
      _inputController.text = prompt;
      _inputController.selection = TextSelection.collapsed(
        offset: prompt.length,
      );
      _inputFocus.requestFocus();
    },
  );

  void _searchHistory(String value) {
    _historySearchTimer?.cancel();
    setState(() {
      _historyQuery = value;
      _historyMatches = null;
    });
    if (value.trim().isEmpty) return;
    _historySearchTimer = Timer(const Duration(milliseconds: 200), () async {
      final matches = await LocalDbService().searchChatIds(value);
      if (mounted && _historyQuery == value) {
        setState(() => _historyMatches = matches);
      }
    });
  }

  Future<void> _loadOlderMessages() async {
    final session = _currentSession;
    if (_loadingOlder || session == null || session.messages.isEmpty) return;
    setState(() => _loadingOlder = true);
    final beforeExtent = _scrollController.hasClients
        ? _scrollController.position.maxScrollExtent
        : 0.0;
    final beforeOffset = _scrollController.hasClients
        ? _scrollController.offset
        : 0.0;
    try {
      final older = await LocalDbService().loadChatMessages(
        session.id,
        limit: 60,
        before: session.messages.first,
      );
      if (!mounted || _currentSession?.id != session.id) return;
      final ids = session.messages.map((m) => m.id).toSet();
      setState(
        () => session.messages.insertAll(
          0,
          older.where((m) => !ids.contains(m.id)),
        ),
      );
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted &&
            _currentSession?.id == session.id &&
            _scrollController.hasClients) {
          final position = _scrollController.position;
          _scrollController.jumpTo(
            (beforeOffset + position.maxScrollExtent - beforeExtent).clamp(
              position.minScrollExtent,
              position.maxScrollExtent,
            ),
          );
        }
      });
    } finally {
      if (mounted) setState(() => _loadingOlder = false);
    }
  }

  Future<void> _archiveSession(ChatSession session) async {
    if (_archivingSessionId != null ||
        (_isSending && _activeSessionId == session.id)) {
      return;
    }
    setState(() => _archivingSessionId = session.id);
    try {
      if (!await confirmChatArchive(context, session) || !mounted) return;
      // Recheck after confirmation in case a command was recovered meanwhile.
      if (_isSending && _activeSessionId == session.id) {
        throw StateError(
          'Wait for Jarvis to finish this chat before archiving it.',
        );
      }
      await LocalChatArchiveService().archiveStoredConversation(session.id);
      final loaded = await _loadVisibleSessions();
      if (!mounted) return;
      setState(() {
        final active = _sessions
            .where((s) => s.id == _activeSessionId)
            .firstOrNull;
        _sessions = loaded
            .map((s) => _isSending && s.id == active?.id ? active! : s)
            .toList();
        _currentSession =
            _sessions.where((s) => s.id == _currentSession?.id).firstOrNull ??
            _currentSession;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Chat archived on this phone. Open Archived beside Recents to see it.',
          ),
        ),
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Could not archive this chat. ${error.toString().replaceFirst('Exception: ', '').replaceFirst('Bad state: ', '')}',
            ),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _archivingSessionId = null);
    }
  }

  Widget _buildHistoryPanel() {
    final sessions = _sessions
        .where(
          (session) =>
              session.title.toLowerCase().contains(
                _historyQuery.toLowerCase(),
              ) ||
              (_historyMatches?.contains(session.id) ?? false) ||
              session.messages.any(
                (m) =>
                    m.text.toLowerCase().contains(_historyQuery.toLowerCase()),
              ),
        )
        .toList();
    return ColoredBox(
      color: AppTheme.sidebar,
      child: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 22, 16, 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Text(
                        'Conversations',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Long-press a chat for options',
                    style: TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 13,
                    ),
                  ),
                  const SizedBox(height: 20),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppTheme.textPrimary,
                        minimumSize: const Size(0, 48),
                        side: const BorderSide(color: AppTheme.border),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                      onPressed: _startNewChat,
                      icon: const Icon(Icons.add_rounded),
                      label: const Text('New conversation'),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _historyController,
                    onChanged: _searchHistory,
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
              child: ChatHistoryList(
                sessions: sessions,
                selectedId: _currentSession?.id,
                workingId: _isSending ? _activeSessionId : null,
                archivingId: _archivingSessionId,
                onSelect: _selectSession,
                onRename: _showRenameDialog,
                onDelete: _confirmDeleteSession,
                onArchive: _archiveSession,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMessageBubble(ChatMessage msg) {
    final isUser = msg.isUser;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 14),
      child: Column(
        crossAxisAlignment: isUser
            ? CrossAxisAlignment.end
            : CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            const Row(
              children: [
                JarvisMark(size: 24),
                SizedBox(width: 9),
                Text(
                  'Jarvis',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                ),
              ],
            ),
            const SizedBox(height: 10),
          ],
          Container(
            constraints: isUser
                ? BoxConstraints(
                    maxWidth: MediaQuery.sizeOf(context).width * 0.78,
                  )
                : null,
            padding: isUser
                ? const EdgeInsets.symmetric(horizontal: 18, vertical: 12)
                : EdgeInsets.zero,
            decoration: isUser
                ? BoxDecoration(
                    color: AppTheme.surfaceBright,
                    borderRadius: const BorderRadius.only(
                      topLeft: Radius.circular(18),
                      topRight: Radius.circular(18),
                      bottomLeft: Radius.circular(18),
                      bottomRight: Radius.circular(6),
                    ),
                  )
                : null,
            child: ChatMessageContent(text: msg.text, isUser: isUser),
          ),
          const SizedBox(height: 6),
          Row(
            mainAxisAlignment: isUser
                ? MainAxisAlignment.end
                : MainAxisAlignment.start,
            children: [
              Text(
                IstTime.clock(msg.timestamp),
                style: const TextStyle(
                  fontSize: 11,
                  color: AppTheme.textSecondary,
                ),
              ),
              if (!isUser && msg.durationMs != null) ...[
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 6),
                  child: Text(
                    '·',
                    style: TextStyle(color: AppTheme.textSecondary),
                  ),
                ),
                Text(
                  _formatReplyDuration(msg.durationMs!),
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppTheme.textSecondary,
                  ),
                ),
              ],
              if (!isUser) ...[
                const Spacer(),
                IconButton(
                  tooltip: 'Copy response',
                  icon: const Icon(Icons.copy_outlined, size: 16),
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: msg.text));
                    if (mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Response copied')),
                      );
                    }
                  },
                ),
              ],
            ],
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
    void submit() {
      if (!_isSending &&
          _archivingSessionId != _currentSession?.id &&
          _restoringHistoryId == null &&
          (_inputController.text.trim().isNotEmpty ||
              _pendingAttachments.isNotEmpty)) {
        _handleSendMessage(_inputController.text);
      }
    }

    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.enter, control: true): submit,
        const SingleActivator(LogicalKeyboardKey.enter, meta: true): submit,
      },
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
          child: ListenableBuilder(
            listenable: _inputFocus,
            builder: (context, child) => AnimatedContainer(
              duration: const Duration(milliseconds: 160),
              padding: const EdgeInsets.fromLTRB(18, 6, 8, 8),
              decoration: BoxDecoration(
                color: AppTheme.surface,
                borderRadius: BorderRadius.circular(20),
                border: Border.all(
                  color: _inputFocus.hasFocus
                      ? AppTheme.primaryLight.withValues(alpha: 0.7)
                      : AppTheme.border,
                ),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.12),
                    blurRadius: 20,
                    offset: const Offset(0, 4),
                  ),
                ],
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
                                            () => _pendingAttachments.remove(
                                              file,
                                            ),
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
                    minLines: 2,
                    maxLines: 5,
                    textCapitalization: TextCapitalization.sentences,
                    keyboardType: TextInputType.multiline,
                    textInputAction: TextInputAction.newline,
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
                        icon: const Icon(Icons.add_rounded, size: 21),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _restoringHistoryId != null
                              ? 'Restoring older messages…'
                              : _isSending
                              ? 'Working on your request…'
                              : 'Your personal assistant',
                          style: const TextStyle(
                            color: AppTheme.textSecondary,
                            fontSize: 11,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      ValueListenableBuilder<TextEditingValue>(
                        valueListenable: _inputController,
                        builder: (context, value, child) => IconButton.filled(
                          tooltip: 'Send message',
                          onPressed:
                              _isSending ||
                                  _archivingSessionId == _currentSession?.id ||
                                  _restoringHistoryId != null ||
                                  (value.text.trim().isEmpty &&
                                      _pendingAttachments.isEmpty)
                              ? null
                              : submit,
                          style: IconButton.styleFrom(
                            backgroundColor: AppTheme.primaryLight,
                            foregroundColor: AppTheme.sidebar,
                            disabledBackgroundColor: AppTheme.surfaceBright,
                            disabledForegroundColor: AppTheme.textSecondary,
                          ),
                          icon: child!,
                        ),
                        child: const Icon(Icons.arrow_upward_rounded, size: 21),
                      ),
                    ],
                  ),
                ],
              ),
            ),
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
}
