import 'package:flutter/material.dart';

import '../data.dart';
import '../models.dart';
import '../theme.dart';
import 'ticker_screen.dart';

/// One column of the comparison table. `value` drives sorting; `format` drives display.
class CompareColumn {
  const CompareColumn(this.label, this.tooltip, this.value, this.format, {this.numeric = true});

  final String label;
  final String tooltip;
  final Object? Function(TickerViews c, Quote? q) value;
  final String Function(Object? v) format;
  final bool numeric;
}

String _pct1(Object? v) {
  if (v is! double) return '–';
  final s = '${(v * 100).toStringAsFixed(1)}%';
  return v >= 0 ? '+$s' : s;
}

String _pct0(Object? v) => v is double ? fmtPct(v) : '–';
String _pctPlain(Object? v) => v is double ? fmtPct(v, signed: false) : '–';
String _text(Object? v) => v?.toString() ?? '–';

double? _stanceScore(Suggestion? s) => switch (s?.stance) {
      Stance.bullish => 1,
      Stance.neutral => 0,
      Stance.bearish => -1,
      null => null,
    };

String _stanceText(Object? v) => switch (v) {
      1.0 => '▲ Bullish',
      0.0 => '■ Neutral',
      -1.0 => '▼ Bearish',
      _ => '–',
    };

double? _price(TickerViews c, Quote? q) => q?.close ?? c.pick?.metric('last_close');

double? _vs(TickerViews c, Quote? q, String level) {
  final p = _price(c, q), l = c.pick?.metric(level);
  return p == null || l == null || l == 0 ? null : p / l - 1;
}

/// Every column a daily check needs, left to right: identity, today's move, trend, the screen's
/// reasons, valuation/quality, then the AI's view.
final compareColumns = <CompareColumn>[
  CompareColumn('#', 'Rank in this week\'s screen', (c, q) => c.pick?.rank.toDouble(),
      (v) => v is double ? '#${v.toInt()}' : '–'),
  CompareColumn('Stock', 'Ticker', (c, q) => c.ticker, _text, numeric: false),
  CompareColumn('Size', 'S&P 500 = large cap, S&P 400 = mid cap',
      (c, q) => switch (c.pick?.metrics['index']) { 'S&P 400' => 'Mid', 'S&P 500' => 'Large', _ => null },
      _text, numeric: false),
  CompareColumn('Sector', 'GICS sector', (c, q) => c.pick?.sector, _text, numeric: false),
  CompareColumn('Price', 'Latest close', _price, (v) => v is double ? '\$${v.toStringAsFixed(2)}' : '–'),
  CompareColumn('Day', 'Change on the latest trading day', (c, q) => q?.dayChange, _pct1),
  CompareColumn('5 days', 'Change over the last 5 trading days', (c, q) => q?.weekChange, _pct1),
  CompareColumn('1 month', 'Return over the last ~21 trading days', (c, q) => c.pick?.metric('ret_1m'), _pct0),
  CompareColumn('Momentum', '12-month return, skipping the latest month (the main ranking signal)',
      (c, q) => c.pick?.metric('mom_12_1'), _pct0),
  CompareColumn('vs S&P 3 mo', '3-month return relative to the S&P 500', (c, q) => c.pick?.metric('rel_3m'), _pct0),
  CompareColumn('Volatility', 'Annualised volatility over 6 months', (c, q) => c.pick?.metric('vol_6m'), _pctPlain),
  CompareColumn('vs 50-day', 'Price relative to its 50-day average', (c, q) => _vs(c, q, 'sma_50'), _pct0),
  CompareColumn('vs 200-day', 'Price relative to its 200-day average', (c, q) => _vs(c, q, 'sma_200'), _pct0),
  CompareColumn('From 52w high', 'How far below its 52-week high', (c, q) => _vs(c, q, 'high_52w'), _pct0),
  CompareColumn('P/E', 'Price / trailing-12-month earnings',
      (c, q) => c.pick?.metric('pe_ttm'), (v) => v is double ? v.toStringAsFixed(1) : '–'),
  CompareColumn('FCF yield', 'Free cash flow / market value', (c, q) => c.pick?.metric('fcf_yield'), _pctPlain),
  CompareColumn('Net margin', 'Trailing-12-month net income / revenue',
      (c, q) => c.pick?.metric('net_margin'), _pctPlain),
  CompareColumn('Rev. growth', 'Revenue growth, year on year',
      (c, q) => c.pick?.metric('revenue_growth_yoy'), _pct0),
  CompareColumn('1–3 mo view', 'AI stance vs the S&P 500, next 1–3 months',
      (c, q) => _stanceScore(c.medium), _stanceText),
  CompareColumn('6–24 mo view', 'AI stance vs the S&P 500, next 6–24 months',
      (c, q) => _stanceScore(c.long), _stanceText),
  CompareColumn('Confidence', 'AI confidence in the 1–3 month view',
      (c, q) => c.medium?.confidence, _pctPlain),
];

/// Sorts cards by one column; missing values always go last.
List<TickerViews> sortCards(List<TickerViews> cards, Map<String, Quote> quotes, CompareColumn col, bool ascending) {
  int cmp(Object a, Object b) =>
      a is num && b is num ? a.compareTo(b) : a.toString().toLowerCase().compareTo(b.toString().toLowerCase());
  return [...cards]..sort((x, y) {
      final a = col.value(x, quotes[x.ticker]), b = col.value(y, quotes[y.ticker]);
      if (a == null && b == null) return 0;
      if (a == null) return 1;
      if (b == null) return -1;
      return ascending ? cmp(a, b) : cmp(b, a);
    });
}

class CompareScreen extends StatefulWidget {
  const CompareScreen({super.key, required this.home, required this.data});

  final HomeData home;
  final DataSource data;

  @override
  State<CompareScreen> createState() => _CompareScreenState();
}

class _CompareScreenState extends State<CompareScreen> {
  int _sortCol = 0; // rank
  bool _asc = true;

  @override
  Widget build(BuildContext context) {
    final home = widget.home;
    final rows = sortCards(home.cards, home.quotes, compareColumns[_sortCol], _asc);
    final dates = home.quotes.values.map((q) => q.date).toList()..sort();
    final priceDate = dates.isEmpty ? null : dates.last.toIso8601String().substring(0, 10);
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Compare picks')),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
        Text(
          'All ${rows.length} picks side by side. Tap a column to sort, tap a row for the chart and full analysis.',
          style: text.bodyMedium?.copyWith(color: TiColors.ink2(context)),
        ),
        const SizedBox(height: 4),
        Text(
          [
            if (priceDate != null) 'Prices: close of $priceDate',
            if (home.run != null) 'AI views: as of ${home.run!.asOf}',
            'Screen numbers are computed in code',
          ].join(' · '),
          style: text.bodySmall?.copyWith(color: TiColors.muted(context)),
        ),
        const SizedBox(height: 12),
        Container(
          decoration: BoxDecoration(
            border: Border.all(color: TiColors.border(context)),
            borderRadius: BorderRadius.circular(12),
          ),
          clipBehavior: Clip.antiAlias,
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              sortColumnIndex: _sortCol,
              sortAscending: _asc,
              headingRowHeight: 44,
              dataRowMinHeight: 40,
              dataRowMaxHeight: 48,
              columnSpacing: 20,
              showCheckboxColumn: false,
              headingTextStyle: text.labelMedium?.copyWith(fontWeight: FontWeight.w700),
              columns: [
                for (final (i, c) in compareColumns.indexed)
                  DataColumn(
                    label: Text(c.label),
                    tooltip: c.tooltip,
                    numeric: c.numeric,
                    onSort: (_, asc) => setState(() {
                      // First tap on a numeric column sorts high-to-low (what you usually want), except rank.
                      _asc = _sortCol == i ? asc : (!c.numeric || i == 0);
                      _sortCol = i;
                    }),
                  ),
              ],
              rows: [
                for (final card in rows)
                  DataRow(
                    onSelectChanged: (_) => Navigator.of(context).push(MaterialPageRoute<void>(
                        builder: (_) => TickerScreen(ticker: card.ticker, data: widget.data))),
                    cells: [
                      for (final c in compareColumns)
                        DataCell(Text(
                          c.format(c.value(card, home.quotes[card.ticker])),
                          style: TextStyle(
                            fontWeight: c.label == 'Stock' ? FontWeight.w700 : FontWeight.w400,
                            fontFeatures: const [FontFeature.tabularFigures()],
                          ),
                        )),
                    ],
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Text(
          'Research output from a learning project, not financial advice. Past momentum does not guarantee '
          'future returns. Check prices with your broker before trading.',
          style: text.bodySmall?.copyWith(color: TiColors.muted(context)),
        ),
      ]),
    );
  }
}
