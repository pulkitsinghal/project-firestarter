import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:{{ project_slug }}_app/bug_report/screenshot.dart';

void main() {
  testWidgets('returns null (never throws) when no boundary is mounted', (tester) async {
    final shot = await captureScreenshotBase64();
    expect(shot, isNull);
  });

  testWidgets('captures the wrapped screen to a base64 PNG', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: ScreenshotBoundary(child: SizedBox(width: 120, height: 120)),
      ),
    );
    await tester.pump();

    String? shot;
    // toImage()/toByteData() are async and need a real async zone.
    await tester.runAsync(() async {
      shot = await captureScreenshotBase64(pixelRatio: 1.0);
    });

    expect(shot, isNotNull);
    expect(shot!, isNotEmpty);
  });
}
