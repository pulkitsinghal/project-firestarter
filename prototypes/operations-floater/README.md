# Operations Floater prototype

Native macOS floating-dashboard prototype, preserved as generic, reusable work.

This archive intentionally contains only reusable source, packaging metadata,
and generic sample state. It contains no runtime dashboard state, account data,
project names, credentials, signing identifiers, or personal information.

Open `OperationsFloater.xcodeproj` to build the native app. The Swift package is
retained as a lightweight source-and-test harness; it does not replace the
signed Xcode application target.

## Shared model and private adapter

The app consumes the canonical contract in `../operations-dashboard/contract/`:
the record arrays `queue`, `tests`, `resourceBudget`, and `signals`, with
per-record `exposure` and `verification`.

An optional runtime snapshot may be placed in the app's sandboxed Application
Support container as `OperationsFloater/dashboard-state.json`. That local path
is resolved by the app at runtime and is never committed or transmitted. The
native adapter rejects unknown contract fields and rejects every `local-only`
record unless it is marked `verified`. Invalid or missing input fails closed to
the committed generic sample.

Window lifecycle, foreground level, pinning, and source provenance are
native-only capabilities. They are deliberately absent from the shared
snapshot. The browser surface never reads or connects to the native app.

## Current behavior

- The dashboard opens visibly in front and defaults to **Keep in front**.
- Turning off **Keep in front** immediately restores normal window level.
- Closing the window, including with Command-W, retains the app; use **Show
  Dashboard** or click the Dock icon to reopen the same window.
- A procedural animated guide is rendered locally. It uses no image feed,
  camera, microphone, network service, analytics, or external transmission.
  Reduce Motion is respected.
- The application target is sandboxed, uses hardened runtime, and includes a
  macOS app icon, encryption declaration, and productivity category.

## Validation

Run the focused source and lifecycle tests:

```bash
swift test
```

Run an unsigned bounded application build:

```bash
xcodebuild \
  -project OperationsFloater.xcodeproj \
  -scheme OperationsFloater \
  -configuration Release \
  CODE_SIGNING_ALLOWED=NO \
  build
```

A distributable archive still requires the owner's unique bundle identifier,
Apple signing team, certificates, and profiles. Those settings are intentionally
not committed.
