import 'package:flutter/material.dart';
import '../../models/chat_session.dart';
import '../theme.dart';

class ChatHistoryList extends StatefulWidget {
  final List<ChatSession> sessions;
  final String? selectedId;
  final String? workingId;
  final String? archivingId;
  final ValueChanged<ChatSession> onSelect;
  final ValueChanged<ChatSession> onRename;
  final ValueChanged<ChatSession> onDelete;
  final ValueChanged<ChatSession>? onArchive;
  const ChatHistoryList({
    super.key,
    required this.sessions,
    this.selectedId,
    this.workingId,
    this.archivingId,
    required this.onSelect,
    required this.onRename,
    required this.onDelete,
    this.onArchive,
  });

  @override
  State<ChatHistoryList> createState() => _ChatHistoryListState();
}

class _ChatHistoryListState extends State<ChatHistoryList> {
  bool archived = false;

  Future<void> _showOptions(ChatSession chat) async {
    if (widget.archivingId == chat.id) return;
    final action = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        top: false,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 12),
                child: Text(
                  chat.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              ListTile(
                leading: const Icon(Icons.edit_outlined),
                title: const Text('Rename'),
                onTap: () => Navigator.pop(sheetContext, 'rename'),
              ),
              if (!chat.isArchived && widget.onArchive != null)
                ListTile(
                  leading: const Icon(Icons.archive_outlined),
                  title: const Text('Archive'),
                  enabled:
                      widget.workingId != chat.id && widget.archivingId == null,
                  onTap: () => Navigator.pop(sheetContext, 'archive'),
                ),
              ListTile(
                leading: const Icon(Icons.delete_outline, color: AppTheme.red),
                title: const Text(
                  'Delete',
                  style: TextStyle(color: AppTheme.red),
                ),
                onTap: () => Navigator.pop(sheetContext, 'delete'),
              ),
            ],
          ),
        ),
      ),
    );
    if (!mounted) return;
    switch (action) {
      case 'rename':
        widget.onRename(chat);
      case 'archive':
        widget.onArchive?.call(chat);
      case 'delete':
        widget.onDelete(chat);
    }
  }

  @override
  Widget build(BuildContext context) {
    final archivedCount = widget.sessions
        .where((chat) => chat.isArchived)
        .length;
    final sessions =
        widget.sessions.where((chat) => chat.isArchived == archived).toList()
          ..sort((a, b) => b.lastActivityAt.compareTo(a.lastActivityAt));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          child: Row(
            children: [
              Expanded(
                flex: 4,
                child: TextButton(
                  onPressed: () => setState(() => archived = false),
                  style: TextButton.styleFrom(
                    backgroundColor: archived
                        ? Colors.transparent
                        : AppTheme.surfaceBright,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    foregroundColor: archived
                        ? AppTheme.textSecondary
                        : AppTheme.textPrimary,
                  ),
                  child: const Text(
                    'Recents',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
              Expanded(
                flex: 6,
                child: TextButton.icon(
                  onPressed: () => setState(() => archived = true),
                  style: TextButton.styleFrom(
                    backgroundColor: archived
                        ? AppTheme.primarySurface
                        : Colors.transparent,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    foregroundColor: archived
                        ? AppTheme.amber
                        : AppTheme.textSecondary,
                  ),
                  icon: const Icon(Icons.archive_outlined, size: 16),
                  label: Text(
                    'Archived ($archivedCount)',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: sessions.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      archived
                          ? 'No archived chats yet'
                          : 'No conversations found',
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: AppTheme.textSecondary),
                    ),
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
                  itemCount: sessions.length,
                  itemBuilder: (context, index) {
                    final chat = sessions[index];
                    final selected = chat.id == widget.selectedId;
                    final status = widget.archivingId == chat.id
                        ? 'Archiving to Drive…'
                        : widget.workingId == chat.id
                        ? 'Jarvis is working…'
                        : chat.isArchived
                        ? 'Archived · saved to Drive'
                        : chat.hasArchive
                        ? 'Includes archived history'
                        : null;
                    return Material(
                      color: chat.isArchived
                          ? AppTheme.amber.withValues(
                              alpha: selected ? 0.15 : 0.06,
                            )
                          : selected
                          ? AppTheme.surfaceBright
                          : Colors.transparent,
                      borderRadius: BorderRadius.circular(8),
                      clipBehavior: Clip.antiAlias,
                      child: ListTile(
                        key: ValueKey('chat-history-${chat.id}'),
                        contentPadding: const EdgeInsets.only(
                          left: 10,
                          right: 10,
                        ),
                        minTileHeight: 48,
                        selected: selected,
                        selectedColor: AppTheme.textPrimary,
                        visualDensity: VisualDensity.compact,
                        leading: chat.isArchived
                            ? const Icon(
                                Icons.archive_outlined,
                                size: 18,
                                color: AppTheme.amber,
                              )
                            : null,
                        title: Text(
                          chat.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: selected
                                ? FontWeight.w600
                                : FontWeight.w400,
                          ),
                        ),
                        subtitle: status == null
                            ? null
                            : Text(
                                status,
                                style: TextStyle(
                                  fontSize: 10,
                                  color: chat.isArchived || chat.hasArchive
                                      ? AppTheme.amber
                                      : AppTheme.textSecondary,
                                ),
                              ),
                        onLongPress: () => _showOptions(chat),
                        onTap: () => widget.onSelect(chat),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}
