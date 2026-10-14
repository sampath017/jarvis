import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../theme.dart';

/// Selectable prose and fenced code, without interpreting message text as HTML.
class ChatMessageContent extends StatelessWidget {
  const ChatMessageContent({
    super.key,
    required this.text,
    this.isUser = false,
  });
  final String text;
  final bool isUser;

  static const _body = TextStyle(
    fontSize: 15,
    height: 1.65,
    color: AppTheme.textPrimary,
  );

  @override
  Widget build(BuildContext context) {
    if (isUser) return SelectableText(text, style: _body);
    final blocks = <Widget>[];
    final fence = RegExp(
      r'^```([^\n`]*)\n([\s\S]*?)(?:^```[ \t]*$|(?![\s\S]))',
      multiLine: true,
    );
    var cursor = 0;
    for (final match in fence.allMatches(text)) {
      if (match.start > cursor) {
        blocks.add(_prose(text.substring(cursor, match.start)));
      }
      blocks.add(
        _CodeBlock(language: match[1]!.trim(), code: match[2]!.trimRight()),
      );
      cursor = match.end;
    }
    if (cursor < text.length) blocks.add(_prose(text.substring(cursor)));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: blocks,
    );
  }

  Widget _prose(String value) {
    final lines = value.trim().split('\n');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: SelectableText.rich(
        TextSpan(
          children: [
            for (var i = 0; i < lines.length; i++) ...[
              if (i > 0) const TextSpan(text: '\n'),
              _line(lines[i]),
            ],
          ],
        ),
        style: _body,
      ),
    );
  }

  TextSpan _line(String line) {
    final heading = RegExp(r'^#{1,6}\s+(.+)$').firstMatch(line);
    final content =
        heading?[1] ?? line.replaceFirst(RegExp(r'^\s*[-*]\s+'), '•  ');
    final spans = <InlineSpan>[];
    final pattern = RegExp(r'(`([^`]+)`|\*\*([^*]+)\*\*|\*([^*]+)\*)');
    var cursor = 0;
    for (final match in pattern.allMatches(content)) {
      if (match.start > cursor) {
        spans.add(TextSpan(text: content.substring(cursor, match.start)));
      }
      spans.add(
        TextSpan(
          text: match[2] ?? match[3] ?? match[4],
          style: match[2] != null
              ? const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 13,
                  backgroundColor: AppTheme.surfaceBright,
                  color: AppTheme.primaryLight,
                )
              : match[3] != null
              ? const TextStyle(fontWeight: FontWeight.w600)
              : const TextStyle(fontStyle: FontStyle.italic),
        ),
      );
      cursor = match.end;
    }
    if (cursor < content.length) {
      spans.add(TextSpan(text: content.substring(cursor)));
    }
    return TextSpan(
      children: spans,
      style: heading == null
          ? null
          : const TextStyle(
              fontSize: 18,
              height: 1.8,
              fontWeight: FontWeight.w600,
            ),
    );
  }
}

class _CodeBlock extends StatelessWidget {
  const _CodeBlock({required this.language, required this.code});
  final String language;
  final String code;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.symmetric(vertical: 12),
    clipBehavior: Clip.antiAlias,
    decoration: BoxDecoration(
      color: AppTheme.sidebar,
      border: Border.all(color: AppTheme.border),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.only(left: 14, right: 4),
          color: AppTheme.surface,
          child: Row(
            children: [
              Expanded(
                child: Text(
                  language.isEmpty ? 'Code' : language,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12,
                    color: AppTheme.textSecondary,
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Copy code',
                icon: const Icon(Icons.copy_outlined, size: 16),
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: code));
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Code copied')),
                    );
                  }
                },
              ),
            ],
          ),
        ),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.all(16),
          child: SelectableText(
            code,
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 13,
              height: 1.6,
              color: AppTheme.textPrimary,
            ),
          ),
        ),
      ],
    ),
  );
}
