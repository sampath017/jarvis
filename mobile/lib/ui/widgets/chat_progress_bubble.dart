import 'dart:async';
import 'package:flutter/material.dart';
import '../../services/command_client.dart';
import '../theme.dart';
import 'workspace_widgets.dart';

/// One evolving status bubble, fed only by actual app and server operations.
class ChatProgressBubble extends StatefulWidget {
  const ChatProgressBubble({super.key, required this.progress, this.onStop});
  final CommandProgress progress;
  final VoidCallback? onStop;
  @override
  State<ChatProgressBubble> createState() => _ChatProgressBubbleState();
}

class _ChatProgressBubbleState extends State<ChatProgressBubble> {
  late Timer _timer;
  int _seconds = 0;
  @override
  void initState() {
    super.initState();
    _seconds = widget.progress.elapsedSeconds;
    _timer = Timer.periodic(
      const Duration(seconds: 1),
      (_) => setState(() => _seconds++),
    );
  }

  @override
  void didUpdateWidget(ChatProgressBubble oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.progress.elapsedSeconds > _seconds) {
      _seconds = widget.progress.elapsedSeconds;
    }
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final steps = widget.progress.steps.reversed.take(3).toList().reversed;
    final elapsed = _seconds < 60
        ? '${_seconds}s'
        : '${_seconds ~/ 60}m ${_seconds % 60}s';
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 10),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const JarvisMark(size: 28),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  'Jarvis',
                  style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                ),
              ),
              Text(
                elapsed,
                style: const TextStyle(
                  color: AppTheme.textSecondary,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          if (steps.isNotEmpty) ...[
            const SizedBox(height: 14),
            for (final step in steps)
              Padding(
                padding: const EdgeInsets.only(bottom: 7),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(top: 5),
                      child: Icon(
                        Icons.circle,
                        size: 5,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        step,
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppTheme.textSecondary,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
          const SizedBox(height: 12),
          Semantics(
            liveRegion: true,
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 200),
              child: Align(
                key: ValueKey(widget.progress.message),
                alignment: Alignment.centerLeft,
                child: Text(
                  widget.progress.message,
                  style: const TextStyle(
                    fontSize: 15,
                    height: 1.4,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            ),
          ),
          if (widget.onStop != null) ...[
            const SizedBox(height: 6),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: widget.onStop,
                icon: const Icon(Icons.stop_rounded, size: 17),
                label: const Text('Stop'),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
