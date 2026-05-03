import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../widgets/ask_javris_bar.dart';
import '../widgets/chat_history_view.dart';
import '../widgets/task_item.dart';
import '../widgets/note_card.dart';
import '../widgets/add_task_bottom_sheet.dart';
import 'chat_tab.dart';
import '../../providers/task_provider.dart';
import '../../providers/note_provider.dart';
import '../../models/note.dart';
import '../../providers/auth_provider.dart';
import '../../providers/chat_provider.dart';
import '../../providers/chat_threads_provider.dart';
import '../../models/chat_thread.dart';
import '../../providers/api_provider.dart';
import 'note_details_screen.dart';
import 'package:uuid/uuid.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({Key? key}) : super(key: key);

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _tabController.addListener(() {
      setState(() {}); // To update FAB and Drawer selection
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  void _showAddTaskBottomSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => const AddTaskBottomSheet(),
    );
  }

  void _addQuickNote() {
    final newNote = Note(
      id: const Uuid().v4(),
      title: '',
      content: '',
      createdAt: DateTime.now(),
    );
    ref.read(noteListProvider.notifier).addNote(newNote);
    Navigator.of(context).push(
      MaterialPageRoute(builder: (context) => NoteDetailsScreen(note: newNote)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF111114),
      drawer: _buildDrawer(),
      appBar: AppBar(
        backgroundColor: const Color(0xFF111114),
        elevation: 0,
        leading: Builder(
          builder: (context) => IconButton(
            icon: const Icon(Icons.menu, color: Color(0xFFF0F0F2)),
            onPressed: () => Scaffold.of(context).openDrawer(),
          ),
        ),
        title: const Text(
          'Javris',
          style: TextStyle(color: Color(0xFFF0F0F2), fontWeight: FontWeight.bold),
        ),
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: const Color(0xFF2563EB),
          labelColor: const Color(0xFF2563EB),
          unselectedLabelColor: const Color(0xFF888888),
          tabs: const [
            Tab(text: 'Tasks'),
            Tab(text: 'Notes'),
            Tab(text: 'Chat'),
          ],
        ),
      ),
      body: Stack(
        children: [
          TabBarView(
            controller: _tabController,
            children: [
              _buildTasksTab(),
              _buildNotesTab(),
              const ChatTab(),
            ],
          ),
        ],
      ),
      floatingActionButton: _tabController.index == 2 ? null : Padding(
        padding: const EdgeInsets.only(bottom: 90.0), // Above the Javris bar
        child: FloatingActionButton(
          onPressed: () {
            if (_tabController.index == 0) {
              _showAddTaskBottomSheet(context);
            } else {
              _addQuickNote();
            }
          },
          backgroundColor: const Color(0xFF2563EB),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          child: const Icon(Icons.add, color: Colors.white),
        ),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.endFloat,
    );
  }

  Widget _buildTasksTab() {
    final tasksAsync = ref.watch(taskListProvider);
    return tasksAsync.when(
      data: (tasks) {
        final activeTasks = tasks.where((t) => !t.isCompleted).toList();
        final completedTasks = tasks.where((t) => t.isCompleted).toList();

        return ListView(
          padding: const EdgeInsets.only(bottom: 120),
          children: [
            if (activeTasks.isNotEmpty) ...[
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Text('MY TASKS', style: TextStyle(fontSize: 10, color: Color(0xFF555555), fontWeight: FontWeight.bold, letterSpacing: 1.5)),
              ),
              ...activeTasks.map((task) => TaskItem(task: task)),
            ],
            if (completedTasks.isNotEmpty) ...[
              const Divider(color: Color(0xFF222222), height: 32, indent: 16, endIndent: 16),
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  title: Text('COMPLETED (${completedTasks.length})', style: const TextStyle(fontSize: 10, color: Color(0xFF555555), fontWeight: FontWeight.bold, letterSpacing: 1.5)),
                  children: completedTasks.map((task) => TaskItem(task: task)).toList(),
                ),
              ),
            ],
            if (tasks.isEmpty)
              const Center(
                child: Padding(
                  padding: EdgeInsets.only(top: 100),
                  child: Text('No tasks yet', style: TextStyle(color: Color(0xFF555555))),
                ),
              ),
          ],
        );
      },
      loading: () => const Center(child: CircularProgressIndicator(color: Color(0xFF2563EB))),
      error: (err, stack) => Center(child: Text('Error: $err', style: const TextStyle(color: Colors.red))),
    );
  }

  Widget _buildNotesTab() {
    final notesAsync = ref.watch(noteListProvider);
    return notesAsync.when(
      data: (notes) {
        if (notes.isEmpty) {
          return const Center(child: Text('No notes yet', style: TextStyle(color: Color(0xFF555555))));
        }
        return ListView.builder(
          padding: const EdgeInsets.fromLTRB(0, 16, 0, 120),
          itemCount: notes.length,
          itemBuilder: (context, index) => NoteCard(
            note: notes[index],
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (context) => NoteDetailsScreen(note: notes[index])),
            ),
          ),
        );
      },
      loading: () => const Center(child: CircularProgressIndicator(color: Color(0xFF2563EB))),
      error: (err, stack) => Center(child: Text('Error: $err', style: const TextStyle(color: Colors.red))),
    );
  }

  Widget _buildDrawer() {
    final user = ref.watch(authStateProvider).value;
    return Drawer(
      backgroundColor: const Color(0xFF111114),
      child: Column(
        children: [
          DrawerHeader(
            decoration: const BoxDecoration(color: Color(0xFF111114)),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                CircleAvatar(
                  radius: 30,
                  backgroundColor: const Color(0xFF2563EB),
                  child: ClipOval(
                    child: Image.network(
                      user?.photoURL ?? '',
                      width: 60,
                      height: 60,
                      fit: BoxFit.cover,
                      errorBuilder: (context, error, stackTrace) => Text(
                        user?.displayName?.substring(0, 1).toUpperCase() ?? 'U',
                        style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  user?.displayName ?? 'Javris User',
                  style: const TextStyle(color: Color(0xFFF0F0F2), fontWeight: FontWeight.bold),
                ),
              ],
            ),
          ),
          _buildDrawerItem(Icons.check_circle_outline, 'Tasks', _tabController.index == 0, () {
            _tabController.animateTo(0);
            Navigator.pop(context);
          }),
          _buildDrawerItem(Icons.lightbulb_outline, 'Notes', _tabController.index == 1, () {
            _tabController.animateTo(1);
            Navigator.pop(context);
          }),
          const Divider(color: Color(0xFF222222), indent: 16, endIndent: 16),
          _buildDrawerItem(Icons.chat_bubble_outline, 'Chat', _tabController.index == 2, () {
            _tabController.animateTo(2);
            Navigator.pop(context);
          }),
          const Divider(color: Color(0xFF222222), indent: 16, endIndent: 16),
          _buildDrawerItem(Icons.settings_outlined, 'Settings', false, () {}),
          _buildDrawerItem(Icons.help_outline, 'Help & Feedback', false, () {}),
          const Divider(color: Color(0xFF222222), indent: 16, endIndent: 16),
          _buildDrawerItem(Icons.logout, 'Sign Out', false, () {
            ref.read(authServiceProvider).signOut();
          }),
          const SizedBox(height: 16),
        ],
      ),
    );
  }

  Widget _buildDrawerItem(IconData icon, String title, bool selected, VoidCallback onTap, {VoidCallback? onLongPress}) {
    return ListTile(
      leading: Icon(icon, color: selected ? const Color(0xFF2563EB) : const Color(0xFF888888)),
      title: Text(
        title,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          color: selected ? const Color(0xFF2563EB) : const Color(0xFFF0F0F2),
          fontWeight: selected ? FontWeight.bold : FontWeight.normal,
          fontSize: 14,
        ),
      ),
      selected: selected,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      onTap: onTap,
      onLongPress: onLongPress,
    );
  }

  void _showRenameChatDialog(BuildContext context, WidgetRef ref, ChatThread thread) {
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
                  // If it's the current chat, use the provider's rename method
                  if (ref.read(chatProvider).currentThread?.id == thread.id) {
                    ref.read(chatProvider.notifier).renameThread(controller.text.trim());
                  } else {
                    // Otherwise update via API service directly
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
}
