import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models.dart';
import '../theme.dart';

/// Opens an http(s) link outside the app. Anything else is ignored.
Future<void> openExternal(BuildContext context, String? url) async {
  final safe = safeUrl(url);
  if (safe == null) return;
  final ok = await launchUrl(Uri.parse(safe), mode: LaunchMode.externalApplication);
  if (!ok && context.mounted) {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Could not open the link')));
  }
}

/// The exact passage a suggestion cites, with a link to the original filing or article.
Future<void> showCitation(BuildContext context, Citation c) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (context) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.6,
      maxChildSize: 0.92,
      builder: (context, controller) => ListView(
        controller: controller,
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 32),
        children: [
          Text('chunk_${c.id} · ${c.ticker} · ${c.label}',
              style: Theme.of(context).textTheme.labelMedium?.copyWith(color: TiColors.muted(context))),
          const SizedBox(height: 6),
          if (c.title != null) Text(c.title!, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          SelectableText(c.content, style: Theme.of(context).textTheme.bodyLarge?.copyWith(height: 1.55)),
          const SizedBox(height: 20),
          if (c.url != null)
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.tonalIcon(
                onPressed: () => openExternal(context, c.url),
                icon: const Icon(Icons.open_in_new, size: 18),
                label: Text(c.source == 'filing' ? 'Open the SEC filing' : 'Open the article'),
              ),
            ),
        ],
      ),
    ),
  );
}
