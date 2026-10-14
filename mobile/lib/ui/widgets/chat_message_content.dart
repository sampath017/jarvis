import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import '../theme.dart';
import 'chat_chart.dart';
import '../../services/satellite_map.dart';
import 'satellite_map_card.dart';

/// GFM prose, tables and native charts. Message content never executes HTML/JS.
class ChatMessageContent extends StatelessWidget {
  const ChatMessageContent({
    super.key,
    required this.text,
    this.isUser = false,
    this.onOpenLink,
    this.satelliteImageLoader,
  });
  final String text;
  final bool isUser;
  final Future<void> Function(Uri)? onOpenLink;
  final SatelliteImageLoader? satelliteImageLoader;

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
    var charts = 0;
    var maps = 0;
    for (final match in fence.allMatches(text)) {
      if (match.start > cursor) {
        blocks.add(_prose(context, text.substring(cursor, match.start)));
      }
      final language = match[1]!.trim();
      final code = match[2]!.replaceFirst(RegExp(r'\r?\n$'), '');
      final chart = language.toLowerCase() == 'chart' && charts < 3
          ? ChatChartData.tryParse(code)
          : null;
      if (chart != null) charts++;
      final map = language.toLowerCase() == 'satellite-map' && maps < 2
          ? SatelliteMapData.tryParse(code)
          : null;
      if (map != null) maps++;
      blocks.add(
        map != null
            ? SatelliteMapCard(data: map, loadImage: satelliteImageLoader)
            : chart == null
            ? _CodeBlock(language: language, code: code)
            : ChatChart(data: chart),
      );
      cursor = match.end;
    }
    if (cursor < text.length) {
      blocks.add(_prose(context, text.substring(cursor)));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: blocks,
    );
  }

  Widget _prose(BuildContext context, String value) {
    // Earlier replies used literal bullet characters. Re-render that saved
    // history with proper list layout while preserving the stored response.
    final markdown = value.trim().replaceAllMapped(
      RegExp(r'^[ \t]*[•‣]\s+', multiLine: true),
      (_) => '- ',
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: MarkdownBody(
        data: markdown,
        selectable: true,
        fitContent: false,
        onTapLink: (_, href, _) => _openLink(context, href),
        // Do not automatically load tracking images or local files from a
        // model-generated URL. The user may explicitly open the image link.
        imageBuilder: (uri, title, alt) => TextButton.icon(
          onPressed: () => _openLink(context, uri.toString()),
          icon: const Icon(Icons.image_outlined, size: 18),
          label: Text(alt?.isNotEmpty == true ? alt! : 'Open image'),
        ),
        styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
          p: _body,
          a: _body.copyWith(
            color: AppTheme.primaryLight,
            decoration: TextDecoration.underline,
          ),
          h1: _body.copyWith(
            fontSize: 23,
            height: 1.3,
            fontWeight: FontWeight.w600,
          ),
          h2: _body.copyWith(
            fontSize: 20,
            height: 1.35,
            fontWeight: FontWeight.w600,
          ),
          h3: _body.copyWith(
            fontSize: 17,
            height: 1.4,
            fontWeight: FontWeight.w600,
          ),
          h1Padding: const EdgeInsets.only(top: 12, bottom: 4),
          h2Padding: const EdgeInsets.only(top: 10, bottom: 4),
          h3Padding: const EdgeInsets.only(top: 8, bottom: 2),
          strong: const TextStyle(fontWeight: FontWeight.w600),
          code: const TextStyle(
            fontFamily: 'monospace',
            fontSize: 13,
            color: AppTheme.primaryLight,
            backgroundColor: AppTheme.surfaceBright,
          ),
          blockSpacing: 12,
          listIndent: 22,
          listBullet: _body,
          tableHead: _body.copyWith(fontSize: 14, fontWeight: FontWeight.w600),
          tableBody: _body.copyWith(fontSize: 14),
          tableHeadAlign: TextAlign.left,
          // Fixed-width columns enable the package's per-table horizontal
          // scroll view instead of compressing a comparison into tiny cells.
          tableColumnWidth: const FixedColumnWidth(160),
          tableScrollbarThumbVisibility: true,
          tableBorder: TableBorder.all(color: AppTheme.border),
          tableCellsPadding: const EdgeInsets.symmetric(
            horizontal: 12,
            vertical: 10,
          ),
          tableHeadCellsDecoration: const BoxDecoration(
            color: AppTheme.surfaceBright,
          ),
          tableCellsDecoration: const BoxDecoration(color: AppTheme.surface),
          blockquotePadding: const EdgeInsets.symmetric(
            horizontal: 14,
            vertical: 8,
          ),
          blockquoteDecoration: const BoxDecoration(
            border: Border(left: BorderSide(color: AppTheme.primary, width: 3)),
          ),
        ),
      ),
    );
  }

  Future<void> _openLink(BuildContext context, String? href) async {
    final uri = Uri.tryParse(href ?? '');
    var opened = false;
    if (uri != null &&
        {'https', 'http'}.contains(uri.scheme) &&
        uri.host.isNotEmpty &&
        uri.userInfo.isEmpty) {
      try {
        if (onOpenLink != null) {
          await onOpenLink!(uri);
          opened = true;
        } else {
          opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
        }
      } catch (_) {
        /* Show a readable failure below, without breaking chat. */
      }
    }
    if (!opened && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("This link couldn't be opened.")),
      );
    }
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
