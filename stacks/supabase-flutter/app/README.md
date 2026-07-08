# {{ project_name }} — Flutter app

The mobile/web client. Runs entirely in Docker — no host Flutter SDK.

```bash
make flutter-analyze        # flutter analyze --fatal-infos
make flutter-format-check   # read-only format check (exits 1 if changes needed)
make flutter-format         # apply dart format in place
make flutter-test           # flutter test
```

Layer rule: the Dart **service layer** (`../services`) owns domain logic and is
the source of truth for app state — widgets render it, they don't re-implement
it.
