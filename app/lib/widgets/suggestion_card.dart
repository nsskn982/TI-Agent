import 'package:flutter/material.dart';

import '../models.dart';
import '../theme.dart';
import 'citation_sheet.dart';

class StanceBadge extends StatelessWidget {
  const StanceBadge(this.stance, {super.key});

  final Stance stance;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: TiColors.border(context)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: TiColors.stance(context, stance), shape: BoxShape.circle)),
        const SizedBox(width: 6),
        Text('${stance.mark} ${stance.label}',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
      ]),
    );
  }
}

class ChangeChip extends StatelessWidget {
  const ChangeChip(this.s, {super.key});

  final Suggestion s;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (text, bg, fg) = switch (s.change) {
      Change.isNew => ('New', TiColors.series1(context), Colors.white),
      Change.changed => ('Changed from ${s.previousStance?.name ?? '?'}', scheme.surfaceContainerHighest, scheme.onSurface),
      _ => ('', Colors.transparent, Colors.transparent),
    };
    if (text.isEmpty) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
      child: Text(text, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: fg)),
    );
  }
}

/// One horizon's view: stance, confidence, thesis, risks and the passages it cites.
class SuggestionCard extends StatelessWidget {
  const SuggestionCard({super.key, required this.s, required this.citations, this.showDate = false});

  final Suggestion s;
  final Map<int, Citation> citations;
  final bool showDate;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: TiColors.border(context)),
        boxShadow: [BoxShadow(color: fade(Colors.black, 0.06), blurRadius: 24, offset: const Offset(0, 10))],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(s.horizonLabel.toUpperCase(),
                style: text.labelSmall?.copyWith(color: TiColors.muted(context), letterSpacing: 0.8)),
            ChangeChip(s),
            StanceBadge(s.stance),
            Text('${(s.confidence * 100).round()}% confidence',
                style: text.bodySmall?.copyWith(color: TiColors.ink2(context))),
            if (showDate) Text('as of ${s.asOf}', style: text.bodySmall?.copyWith(color: TiColors.muted(context))),
          ],
        ),
        const SizedBox(height: 12),
        Text(s.thesis, style: text.bodyLarge?.copyWith(height: 1.5)),
        if (s.risks.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (final r in s.risks)
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('•  ', style: TextStyle(color: TiColors.ink2(context))),
                Expanded(child: Text(r, style: text.bodyMedium?.copyWith(color: TiColors.ink2(context)))),
              ]),
            ),
        ],
        if (s.chunkIds.isNotEmpty) ...[
          const SizedBox(height: 10),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final id in s.chunkIds)
              if (citations[id] case final c?)
                ActionChip(
                  label: Text(c.label, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                  tooltip: c.title ?? c.label,
                  visualDensity: VisualDensity.compact,
                  onPressed: () => showCitation(context, c),
                )
              else
                Chip(
                  label: Text('chunk_$id', style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                  visualDensity: VisualDensity.compact,
                ),
          ]),
        ],
      ]),
    );
  }
}
