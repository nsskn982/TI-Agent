import 'package:flutter/material.dart';

import '../data.dart';
import '../models.dart';
import '../theme.dart';
import '../widgets/contact.dart';
import '../widgets/scroll_scrub.dart';
import '../widgets/suggestion_card.dart';
import 'ticker_screen.dart';

/// This week's suggestions as a scroll story: a hero that fades away, an at-a-glance grid,
/// one scene per ticker whose two views slide in as you scroll, and a contact scene.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.data, this.onSignOut});

  final DataSource data;
  final Future<void> Function()? onSignOut;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<HomeData> _future = loadHome(widget.data);

  Future<void> _reload() async {
    final next = loadHome(widget.data);
    setState(() => _future = next);
    await next;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('TI Agent', style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          const ContactButton(),
          if (widget.onSignOut != null)
            IconButton(tooltip: 'Sign out', icon: const Icon(Icons.logout), onPressed: widget.onSignOut),
          const SizedBox(width: 4),
        ],
      ),
      body: FutureBuilder<HomeData>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return _Message(
              title: 'Could not load suggestions',
              body: 'Check your connection. If this keeps happening, your account may not have access yet.',
              action: FilledButton(onPressed: _reload, child: const Text('Try again')),
            );
          }
          final home = snap.data!;
          return RefreshIndicator(
            onRefresh: _reload,
            child: CustomScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              slivers: [
                SliverToBoxAdapter(child: _Hero(home)),
                if (home.cards.isNotEmpty) SliverToBoxAdapter(child: _Overview(home)),
                for (final (i, c) in home.cards.indexed)
                  SliverToBoxAdapter(child: _TickerScene(c, i, home.cards.length, home.citations, widget.data)),
                const SliverToBoxAdapter(child: _ContactScene()),
                const SliverToBoxAdapter(child: _Disclaimer()),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero(this.home);

  final HomeData home;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final run = home.run;
    final s = home.stats;
    final height = MediaQuery.sizeOf(context).height * 0.78;
    return ScrollScrub(
      start: 0.0, // at rest the hero's top is at the top of the viewport: progress 0
      end: -0.5, // fully faded once its top has scrolled half a screen above the viewport
      rest: 0.0, // with reduce-motion on, keep the hero fully visible
      // At least most of a screen tall, but free to grow: on small phones (or large text settings)
      // the title, text and stats wrap onto more lines than a fixed height could hold.
      builder: (context, t) => ConstrainedBox(
        constraints: BoxConstraints(minHeight: height.clamp(360.0, 760.0).toDouble()),
        child: Stack(alignment: AlignmentDirectional.centerStart, children: [
          Positioned.fill(child: _Orbs(t)),
          Opacity(
            opacity: (1 - t * 1.2).clamp(0.0, 1.0).toDouble(),
            child: Transform.translate(
              offset: Offset(0, -70 * t),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 32, 20, 24),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min,
                    children: [
                  Text(
                    run == null ? 'WEEKLY RESEARCH' : 'WEEKLY RESEARCH · AS OF ${run.asOf} · RUN #${run.id}',
                    style: text.labelSmall?.copyWith(letterSpacing: 1.6, color: TiColors.muted(context)),
                  ),
                  const SizedBox(height: 12),
                  Text("This week's\nsuggestions",
                      style: text.displayMedium?.copyWith(fontWeight: FontWeight.w800, height: 0.98, letterSpacing: -1.5)),
                  const SizedBox(height: 16),
                  Text(
                    run == null
                        ? 'Nothing to show yet. Suggestions appear here after the weekly run.'
                        : 'Two horizons for every ticker, judged against the benchmark. Every claim is cited and every number comes from code.',
                    style: text.titleMedium?.copyWith(color: TiColors.ink2(context), height: 1.4),
                  ),
                  if (run != null) ...[
                    const SizedBox(height: 28),
                    Wrap(spacing: 28, runSpacing: 16, children: [
                      _Stat(s.tickers, 'tickers'),
                      _Stat(s.views, 'views'),
                      _Stat(s.bullish, 'bullish'),
                      _Stat(s.sources, 'cited passages'),
                      if (s.changed > 0) _Stat(s.changed, 'new or changed'),
                    ]),
                    const SizedBox(height: 28),
                    Row(children: [
                      Icon(Icons.keyboard_double_arrow_down, color: TiColors.ink2(context)),
                      const SizedBox(width: 6),
                      Text('Scroll to explore', style: TextStyle(color: TiColors.ink2(context))),
                    ]),
                  ],
                ]),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}

/// Soft colour fields behind the hero; they drift and grow as the hero scrolls away.
class _Orbs extends StatelessWidget {
  const _Orbs(this.t);

  final double t;

  @override
  Widget build(BuildContext context) {
    Widget orb(Color c, double size, Alignment a, double o) => Align(
          alignment: a,
          child: Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(colors: [fade(c, o), fade(c, 0)]),
            ),
          ),
        );
    final w = MediaQuery.sizeOf(context).width;
    return IgnorePointer(
      child: Transform.translate(
        offset: Offset(0, 120 * t),
        child: Transform.scale(
          scale: 1 + 0.3 * t,
          child: Stack(children: [
            orb(TiColors.series1(context), w * 1.1, const Alignment(1.1, -0.6), 0.30),
            orb(TiColors.series2(context), w * 0.8, const Alignment(1.3, 0.8), 0.18),
          ]),
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.value, this.label);

  final int value;
  final String label;

  @override
  Widget build(BuildContext context) {
    final still = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      // Counts up once when the page loads.
      TweenAnimationBuilder<double>(
        tween: Tween(begin: still ? value.toDouble() : 0, end: value.toDouble()),
        duration: const Duration(milliseconds: 1100),
        curve: Curves.easeOutCubic,
        builder: (context, v, _) => Text('${v.round()}',
            style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w700, fontFeatures: [FontFeature.tabularFigures()])),
      ),
      Text(label, style: TextStyle(fontSize: 13, color: TiColors.muted(context))),
    ]);
  }
}

class _Overview extends StatelessWidget {
  const _Overview(this.home);

  final HomeData home;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 40, 20, 24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('At a glance', style: text.headlineLarge?.copyWith(fontWeight: FontWeight.w700, letterSpacing: -0.5)),
        const SizedBox(height: 6),
        Text('Stance relative to the benchmark. Keep scrolling for each thesis and its sources.',
            style: text.bodyMedium?.copyWith(color: TiColors.ink2(context))),
        const SizedBox(height: 20),
        LayoutBuilder(builder: (context, box) {
          final cols = (box.maxWidth / 220).floor().clamp(1, 5).toInt();
          final w = (box.maxWidth - 12 * (cols - 1)) / cols;
          return Wrap(spacing: 12, runSpacing: 12, children: [
            for (final (i, c) in home.cards.indexed)
              ScrollScrub(
                start: 1.0,
                end: 0.75,
                builder: (context, t) {
                  final p = seg(t, (i % cols) * 0.12, 1);
                  return Opacity(
                    opacity: p,
                    child: Transform.translate(offset: Offset(0, 28 * (1 - p)), child: SizedBox(width: w, child: _Tile(c))),
                  );
                },
              ),
          ]);
        }),
      ]),
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile(this.c);

  final TickerViews c;

  @override
  Widget build(BuildContext context) {
    Widget row(String label, Suggestion? s) => s == null
        ? const SizedBox.shrink()
        : Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Row(children: [
              Expanded(
                child: Text(label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 13, color: TiColors.ink2(context))),
              ),
              const SizedBox(width: 6),
              StanceBadge(s.stance),
            ]),
          );
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TiColors.border(context)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(c.ticker, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
        row('1–3 months', c.medium),
        row('6–24 months', c.long),
      ]),
    );
  }
}

class _TickerScene extends StatelessWidget {
  const _TickerScene(this.c, this.index, this.count, this.citations, this.data);

  final TickerViews c;
  final int index, count;
  final Map<int, Citation> citations;
  final DataSource data;

  @override
  Widget build(BuildContext context) {
    final tone = TiColors.stance(context, c.lead);
    final wide = MediaQuery.sizeOf(context).width >= 760;
    final medium = c.medium == null ? null : _slideIn(-1, SuggestionCard(s: c.medium!, citations: citations));
    final long = c.long == null ? null : _slideIn(1, SuggestionCard(s: c.long!, citations: citations));
    return Container(
      decoration: BoxDecoration(
        gradient: RadialGradient(center: const Alignment(-0.8, -0.6), radius: 1.1, colors: [fade(tone, 0.14), fade(tone, 0)]),
      ),
      padding: const EdgeInsets.fromLTRB(20, 56, 20, 40),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        ScrollScrub(
          start: 0.95,
          end: 0.55,
          builder: (context, t) => Opacity(
            opacity: t,
            child: Transform.translate(
              offset: Offset(0, 50 * (1 - t)),
              child: Transform.scale(
                scale: 1.25 - 0.25 * t,
                alignment: Alignment.bottomLeft,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${(index + 1).toString().padLeft(2, '0')} / ${count.toString().padLeft(2, '0')}',
                      style: TextStyle(fontSize: 12, letterSpacing: 1.6, color: TiColors.muted(context))),
                  Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                    Flexible(
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerLeft,
                        child: Text(c.ticker,
                            style: const TextStyle(fontSize: 96, fontWeight: FontWeight.w800, letterSpacing: -4, height: 1)),
                      ),
                    ),
                  ]),
                ]),
              ),
            ),
          ),
        ),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            onPressed: () => Navigator.of(context)
                .push(MaterialPageRoute<void>(builder: (_) => TickerScreen(ticker: c.ticker, data: data))),
            icon: const Icon(Icons.show_chart),
            label: const Text('Chart and history'),
          ),
        ),
        const SizedBox(height: 8),
        if (wide)
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: medium ?? const SizedBox.shrink()),
            const SizedBox(width: 16),
            Expanded(child: long ?? const SizedBox.shrink()),
          ])
        else ...[
          if (medium != null) medium,
          const SizedBox(height: 14),
          if (long != null) long,
        ],
      ]),
    );
  }

  /// Slides a card in from the left (-1) or right (+1) as it scrolls into view.
  Widget _slideIn(int side, Widget child) => ScrollScrub(
        start: 1.0,
        end: 0.6,
        builder: (context, t) => Opacity(
          opacity: t,
          child: Transform.translate(offset: Offset(side * 80 * (1 - t), 0), child: child),
        ),
      );
}

class _ContactScene extends StatelessWidget {
  const _ContactScene();

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return ScrollScrub(
      start: 1.0,
      end: 0.7,
      builder: (context, t) => Opacity(
        opacity: t,
        child: Transform.translate(
          offset: Offset(0, 30 * (1 - t)),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 72, 20, 40),
            child: Column(children: [
              Text('CONTACT', style: text.labelSmall?.copyWith(letterSpacing: 1.6, color: TiColors.muted(context))),
              const SizedBox(height: 8),
              Text('Get in touch', style: text.headlineLarge?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Text('Questions about the project, the method or the code? Reach out.',
                  textAlign: TextAlign.center, style: text.bodyMedium?.copyWith(color: TiColors.ink2(context))),
              const SizedBox(height: 24),
              const ContactButtons(),
            ]),
          ),
        ),
      ),
    );
  }
}

class _Disclaimer extends StatelessWidget {
  const _Disclaimer();

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
        child: Text(
          'Research output from a learning project, not financial advice. TI Agent never places trades.',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: TiColors.muted(context)),
        ),
      );
}

class _Message extends StatelessWidget {
  const _Message({required this.title, required this.body, this.action});

  final String title, body;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            Text(body, textAlign: TextAlign.center),
            if (action != null) ...[const SizedBox(height: 16), action!],
          ]),
        ),
      );
}
