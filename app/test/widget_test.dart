import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ti_agent/data.dart';
import 'package:ti_agent/models.dart';
import 'package:ti_agent/screens/compare_screen.dart';
import 'package:ti_agent/screens/home_screen.dart';
import 'package:ti_agent/theme.dart';

import 'fake_data.dart';

Widget _app(Widget home, {Brightness b = Brightness.light}) =>
    MaterialApp(theme: buildTheme(b), home: home);

void main() {
  testWidgets('compare screen shows every pick with prices and sorts by a column', (tester) async {
    tester.view.physicalSize = const Size(1400, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final data = FakeData(
      screen: const ScreenResult(asOf: '2026-11-14', screened: 900, picks: {
        'MSFT': ScreenPick(ticker: 'MSFT', rank: 1, metrics: {'mom_12_1': 0.62, 'index': 'S&P 500', 'pe_ttm': 31.4}),
        'AAPL': ScreenPick(ticker: 'AAPL', rank: 2, metrics: {'mom_12_1': 0.30, 'index': 'S&P 400', 'pe_ttm': 18.2}),
      }),
    );
    final home = await loadHome(data);
    await tester.pumpWidget(_app(CompareScreen(home: home, data: data)));
    await tester.pumpAndSettle();

    expect(find.text('#1'), findsOneWidget);
    expect(find.text('Large'), findsOneWidget);
    expect(find.text('Mid'), findsOneWidget);
    expect(find.text('31.4'), findsOneWidget);
    expect(find.text('\$110.00'), findsNWidgets(2)); // latest close from the daily prices
    expect(find.text('+10.0%'), findsNWidgets(2)); // day change 100 -> 110
    expect(find.text('▼ Bearish'), findsOneWidget); // MSFT's 1-3 month view

    await tester.tap(find.text('P/E'));
    await tester.pumpAndSettle();
    final stocks = tester.widgetList<Text>(find.byType(Text)).map((t) => t.data).where((s) => s == 'MSFT' || s == 'AAPL');
    expect(stocks.first, 'MSFT'); // highest P/E first
  });

  testWidgets('home shows hero, every ticker scene, views and contact', (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(_app(HomeScreen(data: FakeData())));
    await tester.pumpAndSettle();

    expect(find.text("This week's\nsuggestions"), findsOneWidget);
    expect(find.text('At a glance'), findsOneWidget);
    expect(find.text('AAPL'), findsWidgets);
    expect(find.text('MSFT'), findsWidgets);
    expect(find.textContaining('Revenue grew 15.1%'), findsNWidgets(3));
    expect(find.text('New'), findsNWidgets(3));
    expect(find.text('10-K 2026-11-03'), findsWidgets); // resolved citation chip
    expect(find.text('chunk_99'), findsOneWidget); // missing passage shown, not linked
    expect(find.text('Contact'), findsOneWidget);
    expect(find.textContaining('not financial advice'), findsOneWidget);
  });

  testWidgets('tapping a citation opens the passage', (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(_app(HomeScreen(data: FakeData())));
    await tester.pumpAndSettle();
    final chip = find.text('10-K 2026-11-03').first;
    await tester.ensureVisible(chip);
    await tester.pumpAndSettle();
    await tester.tap(chip);
    await tester.pumpAndSettle();
    expect(find.text('Greater China net sales decreased...'), findsOneWidget);
    expect(find.text('Open the SEC filing'), findsOneWidget);
  });

  testWidgets('reduce-motion shows everything fully, hero included', (tester) async {
    tester.platformDispatcher.accessibilityFeaturesTestValue = const FakeAccessibilityFeatures(disableAnimations: true);
    addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);
    tester.view.physicalSize = const Size(400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(_app(HomeScreen(data: FakeData()), b: Brightness.dark));
    await tester.pumpAndSettle();
    final opacities = tester.widgetList<Opacity>(find.byType(Opacity)).map((o) => o.opacity);
    expect(opacities, isNotEmpty);
    expect(opacities.every((o) => o == 1.0), isTrue);
  });
}
