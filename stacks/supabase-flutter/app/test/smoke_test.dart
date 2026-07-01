// {{ project_name }} — widget smoke test.
// Boots the app and asserts the home screen renders. Grow this alongside
// app/lib as real screens land; it keeps `flutter test` (and CI) meaningful.
import 'package:flutter_test/flutter_test.dart';

import 'package:{{ project_slug }}_app/main.dart';

void main() {
  testWidgets('app boots and renders the home screen', (tester) async {
    await tester.pumpWidget(const PilgrimApp());

    // AppBar shows the project name; the body shows the tagline.
    expect(find.text('{{ project_name }}'), findsWidgets);
    expect(find.text('{{ project_tagline }}'), findsOneWidget);
  });
}
