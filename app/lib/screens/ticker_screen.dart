import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../config.dart';
import '../data.dart';
import '../models.dart';
import '../theme.dart';
import '../widgets/suggestion_card.dart';

class _TickerData {
  const _TickerData(this.ticker, this.bench, this.history, this.citations);

  final List<IndexedPoint> ticker, bench;
  final List<Suggestion> history;
  final Map<int, Citation> citations;
}

/// One ticker: 12-month chart against the benchmark (both indexed to 100) and its suggestion history.
class TickerScreen extends StatefulWidget {
  const TickerScreen({super.key, required this.ticker, required this.data, this.benchmark = AppConfig.benchmark});

  final String ticker;
  final String benchmark;
  final DataSource data;

  @override
  State<TickerScreen> createState() => _TickerScreenState();
}

class _TickerScreenState extends State<TickerScreen> {
  late final Future<_TickerData> _future = _load();

  Future<_TickerData> _load() async {
    final results = await Future.wait([
      widget.data.prices(widget.ticker),
      widget.data.prices(widget.benchmark),
    ]);
    final history = await widget.data.tickerHistory(widget.ticker);
    final cites = await widget.data.citations([for (final s in history) ...s.chunkIds]);
    return _TickerData(rebase(results[0]), rebase(results[1]), history, cites);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text(widget.ticker)),
      body: FutureBuilder<_TickerData>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
          if (snap.hasError) return const Center(child: Text('Could not load this ticker.'));
          final d = snap.data!;
          return ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
            Text('${widget.ticker} vs ${widget.benchmark}, last 12 months', style: text.titleMedium),
            const SizedBox(height: 2),
            Text('Adjusted close, both indexed to 100 at the start of the window.',
                style: text.bodySmall?.copyWith(color: TiColors.muted(context))),
            const SizedBox(height: 10),
            _Legend(widget.ticker, widget.benchmark),
            const SizedBox(height: 8),
            SizedBox(
              height: 260,
              child: d.ticker.isEmpty
                  ? const Center(child: Text('No prices yet.'))
                  : _Chart(d.ticker, d.bench, widget.ticker, widget.benchmark),
            ),
            const SizedBox(height: 28),
            Text('History', style: text.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            if (d.history.isEmpty) const Text('No suggestions for this ticker yet.'),
            for (final s in d.history)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: SuggestionCard(s: s, citations: d.citations, showDate: true),
              ),
          ]);
        },
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend(this.ticker, this.bench);

  final String ticker, bench;

  @override
  Widget build(BuildContext context) {
    Widget item(Color c, String label) => Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 16, height: 2, color: c),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(fontSize: 13, color: TiColors.ink2(context))),
        ]);
    return Wrap(spacing: 16, children: [item(TiColors.series1(context), ticker), item(TiColors.series2(context), bench)]);
  }
}

class _Chart extends StatelessWidget {
  const _Chart(this.ticker, this.bench, this.tickerName, this.benchName);

  final List<IndexedPoint> ticker, bench;
  final String tickerName, benchName;

  static const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  @override
  Widget build(BuildContext context) {
    // x = trading-day index of the ticker series; the benchmark is aligned to the same dates.
    final benchByDate = {for (final p in bench) p.date: p};
    final tSpots = [for (final (i, p) in ticker.indexed) FlSpot(i.toDouble(), p.value)];
    final bSpots = [
      for (final (i, p) in ticker.indexed)
        if (benchByDate[p.date] case final b?) FlSpot(i.toDouble(), b.value),
    ];
    final muted = TiColors.muted(context);
    final labelStyle = TextStyle(fontSize: 11, color: muted);
    final step = (ticker.length / 6).ceilToDouble().clamp(1.0, double.infinity).toDouble();

    LineChartBarData line(List<FlSpot> spots, Color c) => LineChartBarData(
          spots: spots,
          color: c,
          barWidth: 2,
          isCurved: false,
          dotData: const FlDotData(show: false),
        );

    return LineChart(
      LineChartData(
        gridData: FlGridData(
          drawVerticalLine: false,
          getDrawingHorizontalLine: (_) => FlLine(color: TiColors.grid(context), strokeWidth: 1),
        ),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 36,
              getTitlesWidget: (v, meta) => Text(v.toStringAsFixed(0), style: labelStyle),
            ),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 24,
              interval: step,
              getTitlesWidget: (v, meta) {
                final i = v.round();
                if (i < 0 || i >= ticker.length || v != i.toDouble()) return const SizedBox.shrink();
                final d = ticker[i].date;
                return Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text("${_months[d.month - 1]} '${(d.year % 100).toString().padLeft(2, '0')}", style: labelStyle),
                );
              },
            ),
          ),
        ),
        lineTouchData: LineTouchData(
          touchTooltipData: LineTouchTooltipData(
            getTooltipColor: (_) => Theme.of(context).colorScheme.surface,
            tooltipBorder: BorderSide(color: TiColors.border(context)),
            getTooltipItems: (spots) => [
              for (final s in spots)
                LineTooltipItem(
                  '${s.barIndex == 0 ? tickerName : benchName}: ${s.y.toStringAsFixed(1)}'
                  '${s.barIndex == 0 ? ' (\$${ticker[s.x.round()].price.toStringAsFixed(2)})' : ''}',
                  TextStyle(color: Theme.of(context).colorScheme.onSurface, fontSize: 12),
                ),
            ],
          ),
        ),
        lineBarsData: [line(tSpots, TiColors.series1(context)), line(bSpots, TiColors.series2(context))],
      ),
    );
  }
}
