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
the committed generic sample. Imports must be regular files no larger than one
megabyte.

Choose **Import Local Snapshot…** to select and install a canonical local file.
The app does not retain the selected source path. Installation validates before
writing, uses private file permissions, and retains the previous valid snapshot.
Choose **Restore Previous Snapshot** to swap back without weakening validation.

Window lifecycle, foreground level, pinning, and source provenance are
native-only capabilities. They are deliberately absent from the shared
snapshot. The browser surface never reads or connects to the native app.

## Shared presentation structure

The native and web dashboards use the same information hierarchy without
sharing runtime code or creating a device bridge:

1. resource-budget evidence;
2. sortable queue race lanes for running, queued, waiting, and ready work; and
3. compact tests-and-quality and signals panels.

The native surface adds a local queue guide and window controls. At widths of
560 points or more, operational panels use a dense two-column grid; below that
breakpoint, they collapse deterministically to one column. The canonical
snapshot remains schema version `1.0`.

## Current behavior

- The dashboard opens visibly in front and defaults to **Keep in front**.
- Turning off **Keep in front** immediately restores normal window level.
- Closing the window, including with Command-W, retains the app; use **Show
  Dashboard** or click the Dock icon to reopen the same window.
- A procedural animated guide summarizes only canonical state. Verified
  failures and attention signals take priority; unverified failures do not
  become attention cues.
- Guide motion is a deterministic function of time and canonical state. Reduce
  Motion produces a fully stable frame.
- The guide uses no image feed, camera, microphone, network service, analytics,
  or external transmission.
- Queue work appears on a 0-to-100 percent rail. Its rectangular chip animates
  as verified step evidence changes; adding steps can move the chip backward
  without erasing completed work. Hovering shows the full summary and clicking
  the chip or **Details** expands the lane.
- Queue races can retain source order or sort by last activity, completion,
  memory, CPU, or a deterministic needs-attention score. Missing evidence sorts
  last and is labeled unavailable rather than estimated.
- The default 620-by-640 window shows a dense two-column operational grid and
  remains usable down to a 380-by-480 compact single-column layout.
- The application target is sandboxed, uses hardened runtime, and includes a
  macOS app icon, encryption declaration, and productivity category.

See [INSTALL_UPDATE_ROLLBACK.md](INSTALL_UPDATE_ROLLBACK.md) for the release
preflight, local update procedure, acceptance checks, and rollback path.

## Validation

Run the focused source, deterministic-guide, compact-layout, privacy, and
lifecycle tests:

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
