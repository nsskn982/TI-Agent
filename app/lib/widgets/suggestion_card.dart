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
        if (s.bullCase != null)
          _Section('Bull case', Icons.trending_up, body: s.bullCase, accent: TiColors.series1(context)),
        if (s.bearCase != null)
          _Section('Bear case', Icons.trending_down,
              body: s.bearCase, accent: TiColors.stance(context, Stance.bearish)),
        if (s.valuation != null) _Section('Valuation', Icons.balance, body: s.valuation),
        if (s.catalysts.isNotEmpty) _Section('Catalysts to watch', Icons.event, items: s.catalysts),
        if (s.risks.isNotEmpty && s.hasWriteUp) _Section('Risks', Icons.warning_amber_rounded, items: s.risks),
        if (s.risks.isNotEmpty && !s.hasWriteUp) ...[
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

/// One labelled part of the write-up: a paragraph or a bullet list.
class _Section extends StatelessWidget {
  const _Section(this.label, this.icon, {this.body, this.items = const [], this.accent});

  final String label;
  final IconData icon;
  final String? body;
  final List<String> items;
  final Color? accent;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final ink2 = TiColors.ink2(context);
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(icon, size: 16, color: accent ?? ink2),
          const SizedBox(width: 6),
          Text(label, style: text.labelLarge?.copyWith(fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 4),
        if (body != null) Text(body!, style: text.bodyMedium?.copyWith(height: 1.5, color: ink2)),
        for (final i in items)
          Padding(
            padding: const EdgeInsets.only(bottom: 3),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('•  ', style: TextStyle(color: ink2)),
              Expanded(child: Text(i, style: text.bodyMedium?.copyWith(color: ink2))),
            ]),
          ),
      ]),
    );
  }
}
