# Operations Floater prototype

Native macOS floating-dashboard prototype, preserved as generic, reusable work.

This archive intentionally contains only reusable source, packaging metadata, and
generic sample state. It contains no runtime dashboard state, account data,
project names, credentials, or personal information.

Open `OperationsFloater.xcodeproj` to build the native app. The Swift package is
retained only as a lightweight source-build harness; it does not replace the
signed Xcode application target.

## Current prototype behavior

- A native floating dashboard window opens in front of ordinary desktop apps.
- The user can turn off **Keep in front** at any time.
- Closing the window (including with Command-W) keeps the lightweight app
  available; choose **Show Dashboard** from its app or Window menu, or click its
  Dock icon to reopen it.
- A small animated, procedural queue-guide character is rendered locally in the
  dashboard. It uses no image assets, camera, microphone, video capture,
  network service, analytics, or personal data. Reduce Motion is respected.
- Queue data is read only from the sandboxed local Application Support file. If
  no valid local file is present, the dashboard visibly identifies and displays
  privacy-neutral generic sample data.
- The application target is sandboxed, uses hardened runtime, and carries the
  productivity category metadata required for App Store packaging.

For an unsigned local verification build:

```bash
xcodebuild \
  -project OperationsFloater.xcodeproj \
  -scheme OperationsFloater \
  -configuration Release \
  CODE_SIGNING_ALLOWED=NO \
  build
```
