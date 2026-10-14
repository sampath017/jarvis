import 'package:flutter/material.dart';
import '../theme.dart';
import 'workspace_widgets.dart';

class ChatWelcome extends StatelessWidget {
  const ChatWelcome({super.key, required this.onPrompt});
  final ValueChanged<String> onPrompt;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) => SingleChildScrollView(
      child: ConstrainedBox(
        constraints: BoxConstraints(minHeight: constraints.maxHeight),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const JarvisMark(size: 52),
              const SizedBox(height: 24),
              Text(
                MediaQuery.textScalerOf(context).scale(14) > 18
                    ? 'How can I help today?'
                    : 'A little more clarity.\nA little less effort.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                  fontSize: constraints.maxWidth < 400 ? 30 : 38,
                  fontWeight: FontWeight.w400,
                  height: 1.18,
                  letterSpacing: -1.2,
                ),
              ),
              if (MediaQuery.textScalerOf(context).scale(14) <= 18) ...[
                const SizedBox(height: 16),
                const Text(
                  'How can I help today?',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AppTheme.textSecondary, fontSize: 15),
                ),
              ],
              const SizedBox(height: 32),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 8,
                runSpacing: 10,
                children: [
                  _suggestion(
                    Icons.alarm_outlined,
                    'Set a reminder',
                    'Remind me to ',
                  ),
                  _suggestion(
                    Icons.route_outlined,
                    'Review my activity',
                    'What did I do in the last 10 minutes?',
                  ),
                  _suggestion(
                    Icons.note_alt_outlined,
                    'Save a note',
                    'Remember that ',
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget _suggestion(IconData icon, String label, String prompt) =>
      OutlinedButton.icon(
        onPressed: () => onPrompt(prompt),
        icon: Icon(icon, size: 17, color: AppTheme.primaryLight),
        label: Text(label),
        style: OutlinedButton.styleFrom(
          foregroundColor: AppTheme.textPrimary,
          backgroundColor: AppTheme.surface,
          side: const BorderSide(color: AppTheme.border),
          minimumSize: const Size(0, 48),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          textStyle: const TextStyle(
            fontFamily: 'Roboto',
            fontSize: 12,
            fontWeight: FontWeight.w500,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      );
}
