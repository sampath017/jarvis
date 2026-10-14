import 'chat_storage_service.dart';
import 'local_db_service.dart';

class LocalChatArchiveService {
  Future<void> archiveStoredConversation(String threadId) async {
    final full = await ChatStorageService.loadSession(threadId);
    if (full == null) throw StateError('Conversation is no longer available');
    await LocalDbService().cacheArchivedChat(full.toJson(), 'local:$threadId', retirePending:true);
  }
  Future<bool> needsRestore(String threadId) async => false;
  Future<void> restoreHistory(String threadId) async {}
}
