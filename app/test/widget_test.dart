import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ti_agent/screens/home_screen.dart';
import 'package:ti_agent/theme.dart';

import 'fake_data.dart';

Widget _app(Widget home, {Brightness b = Brightness.light}) =>
    MaterialApp(theme: buildTheme(b), home: home);

void main() {
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
