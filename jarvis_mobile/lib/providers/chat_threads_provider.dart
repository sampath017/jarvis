import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/chat_thread.dart';
import '../services/api_service.dart';

final chatThreadsProvider = FutureProvider<List<ChatThread>>((ref) async {
  final apiService = ApiService();
  return await apiService.fetchChatThreads();
});
