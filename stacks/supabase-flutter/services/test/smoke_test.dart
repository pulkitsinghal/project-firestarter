import 'package:test/test.dart';
import 'package:{{ project_slug }}_services/{{ project_slug }}_services.dart';

void main() {
  test('greeting carries the project slug', () {
    expect(greeting(), contains('{{ project_slug }}'));
  });
}
