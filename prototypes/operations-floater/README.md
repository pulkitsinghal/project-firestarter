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

The native app first polls only the fixed loopback Router metrics endpoint at
`http://127.0.0.1:11500/metrics` and accepts its nested `operations` object only
when it is a verified canonical `local` snapshot. It sends no credentials,
cookies, dashboard state, or private file content, and follows no redirect.

An optional runtime snapshot may also be placed in the app's
Application Support directory as `OperationsFloater/dashboard-state.json`.
That local path is resolved by the app at runtime and is never committed or
transmitted. The native adapter rejects unknown contract fields and rejects
every `local-only` record unless it is marked `verified`. Invalid or missing
live and saved input fails closed to an empty dashboard; the committed generic
sample remains storyboard/test data only. Imports must be regular files no
larger than one megabyte.

The additive receipt-backed task view reads only content-addressed
receipt-feed 1.1 files from the app's local
`OperationsFloater/receipts` Application Support directory. It verifies the
current pointer and snapshot SHA-256, rejects duplicate keys and unknown
contract fields, requires allowlisted root-excluded provenance, and falls back
to an independently verified LKG only when current input is invalid. A valid
stale current feed remains selected and is visibly marked stale. Feed absence
or failure makes only this panel unavailable; it never disables the established
dashboard, Router, voice, or window behavior.

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
3. a receipt-backed NOW, DECISIONS, and RECENTLY DONE view; and
4. compact tests-and-quality and signals panels.

The native surface adds a local queue guide and window controls. At widths of
560 points or more, operational panels use a dense two-column grid; below that
breakpoint, they collapse deterministically to one column. The canonical
snapshot remains schema version `1.0`.

## Current behavior

- An explicit user launch opens visibly in front but defaults **Keep in front**
  to off and stays on one macOS Desktop. Pinning and showing the same window on
  every Desktop are never implicit.
- The app holds one process-scoped lease in its Application Support
  directory. A direct second launch activates the existing bundle instance and
  exits before starting another application host.
- A deliberate `--background-ui-test` launch mode leaves **Keep in front** off,
  stays on one macOS Desktop, and neither activates the app nor force-orders its
  window above unrelated work. Normal user launches retain the foreground
  behavior above.
- Turning off **Keep in front** immediately restores normal window level.
- Every major dashboard component has a header collapse control. Collapsed state
  persists locally across relaunches. Hidden operational sections stop snapshot
  refresh work when all of them are collapsed; collapsing Assistant Chat stops
  voice, cancels pending work, revokes the module floor, and clears its
  ephemeral session instead of merely hiding it.
- The receipt view has independent persisted collapse state and never performs
  a control-plane action. It displays only bounded allowlisted labels and
  status fields plus a current, stale, LKG, or offline provenance indicator.
- Closing the window, including with Command-W, retains the app; use **Show
  Dashboard** or click the Dock icon to reopen the same window.
- A procedural animated guide summarizes only canonical state. Verified
  failures and attention signals take priority; unverified failures do not
  become attention cues.
- Guide motion is a deterministic function of time and canonical state. Reduce
  Motion produces a fully stable frame.
- The guide itself uses no image feed, camera, microphone, network service,
  analytics, or external transmission.
- A dismissible corner companion ("Ember") restates the same canonical state as
  one friendly character. It naps when the queue is empty, perks up while lanes
  run, briefly celebrates when work reaches the finished lane, and looks
  concerned on a verified failure, attention signal, or pending owner decision.
  A short status bubble restates only canonical lane counts.
- The companion is vector-drawn with SwiftUI Canvas and uses no image asset,
  camera, microphone, network service, analytics, or external transmission. Its
  mood, pose, motion, and status line are deterministic functions of the
  snapshot and time; Reduce Motion produces a fully stable frame, and it can be
  dismissed to a small wake button. See [docs/COMPANION.md](docs/COMPANION.md).
- Queue work appears on a 0-to-100 percent rail. Its rectangular chip animates
  as verified step evidence changes; adding steps can move the chip backward
  without erasing completed work. Hovering shows the full summary and clicking
  the chip or **Details** expands the lane.
- Queue races can retain source order or sort by last activity, completion,
  memory, CPU, or a deterministic needs-attention score. Missing evidence sorts
  last and is labeled unavailable rather than estimated.
- The assistant panel is disabled by default. After explicit enablement, its
  non-persistent in-app chat talks only to the fixed local AI Router endpoint at
  `http://127.0.0.1:11500/v1/chat/completions` with model `auto`. The app sends
  no provider key, Relay token, dashboard snapshot, or stored file. The Router
  owns model choice and any separately configured, policy-guarded escalation.
- Every assistant bubble keeps its own bounded responder provenance. The label
  comes only from Router-reported `responder.kind` or `responder.provider`
  fields and is closed to **Claude**, **Codex**, or **local-LLM**, with the
  reported model when available. Model text alone is never used to infer
  identity. Missing, malformed, or other provider metadata fails closed without
  adding an assistant bubble.
- Reply monitoring is independently default-off. When enabled, or when
  **Review** is clicked, a second Router-selected request checks whether the
  reply answered the request, stayed evidence-aware, and gave a useful next
  action. Concrete failures receive an in-memory **Assistant Coach** suggestion.
  Critiques are advisory and never block or replace the original answer.
- Chat fails visibly when the local Router is unavailable; it never falls back
  to an arbitrary host or direct provider endpoint, follows no redirects, and
  uses an ephemeral no-cache session.
- The chat composer is a multiline text area: **Return** sends a non-empty
  draft, while **Shift-Return** inserts a newline without contacting the
  Router. The same behavior is exposed as an accessibility hint.
- A compiled static module allowlist can give exactly one bounded conversation
  module the floor. Modules provide no UI, mic, TTS, persistence, screen capture,
  input injection, executable replay, arbitrary network, or dynamic code.
  Escape or **Return to dashboard** revokes the floor. The built-in synthetic
  checkpoint module provides deterministic contract testing.
- Voice conversation is separately explicit and default-off. Production speech
  recognition requires an on-device provider and fails closed when permission,
  provider metadata, or on-device support is unavailable. Start, pause, resume,
  stop, listening, thinking, and responding states remain visible. Optional
  local spoken replies are default-off and interruptible. Each non-empty
  on-device transcript update is staged immediately as a pending **You**
  bubble, then follows the same host send path after exactly 2.000 seconds
  without another update. This does not depend on Apple's optional final-result
  signal. A visible linear countdown resets whenever speech resumes. Every
  human and assistant bubble shows its local creation time beside the reported
  sender. Pause, stop, floor revoke, module switch, clear, and window teardown
  cancel the pending turn; transcript/session memory is ephemeral.
- The UI warns that private or patient data must not be entered because an
  already-configured Router escalation may leave the device. Router policy
  remains the authoritative egress guard.
- The default 620-by-640 window shows a dense two-column operational grid and
  remains usable down to a 380-by-480 compact single-column layout.
- The application target uses the Hardened Runtime and is distributed directly
  with a Developer ID, and includes a macOS app icon, encryption declaration,
  and productivity category. See [docs/SIGNING.md](docs/SIGNING.md) for the
  distribution posture, entitlements, and owner signing steps.
- The supported release shape is one signed main app with no login item,
  launch agent, daemon, privileged helper, or updater. Permission grants bind to
  that app's stable code identity; unsigned and ad-hoc routine builds are
  disposable test artifacts and must not replace or launch as the permission-
  bearing installed copy.

See [INSTALL_UPDATE_ROLLBACK.md](INSTALL_UPDATE_ROLLBACK.md) for the release
preflight, local update procedure, acceptance checks, and rollback path.
See
[`docs/PERMISSION_AND_INSTALL_LIFECYCLE.md`](docs/PERMISSION_AND_INSTALL_LIFECYCLE.md)
for the stable signed code identity, no-helper contract, single-instance
lifecycle, and owner-gated migration plan.
See [docs/BACKGROUND_UI_TESTING.md](docs/BACKGROUND_UI_TESTING.md) for the
low-disruption spare-Desktop test workflow and its measured limitations.
See
[docs/CONVERSATION_MODULE_CONTRACT.md](docs/CONVERSATION_MODULE_CONTRACT.md)
for the versioned module manifest, exact IPC envelope and bounds, floor
lifecycle, privacy posture, and failure behavior.
See [docs/RECEIPT_FEED_NATIVE.md](docs/RECEIPT_FEED_NATIVE.md) for the pinned
native receipt contract, selection semantics, privacy boundary, and rollback.

## Validation

Run the focused source, deterministic-guide, compact-layout, loopback-chat,
privacy, and lifecycle tests:

```bash
swift test
bash Tests/permission-identity-preflight.test.sh
```

Render a still-frame gallery of every companion mood. This rasterizes offscreen
and writes a PNG without opening or foregrounding a dashboard window:

```bash
swift run OperationsFloater --render-companion-preview /tmp/ember-gallery.png
```

Routine validation stops at SwiftPM and synthetic fixture tests on the active
macOS user profile. Xcode 26.5 runs `lsregister` for both `build` and `archive`,
including when `REGISTER_WITH_LAUNCH_SERVICES=NO` is supplied. Do not rely on
that setting to isolate a disposable app bundle. App-bundle compilation belongs
on a disposable macOS account or CI runner; a signed release archive remains an
owner-gated operation.

A synthetic still-frame walkthrough and compact composer/provenance state map live in
[`docs/CHAT_COMPOSER_STATE.md`](docs/CHAT_COMPOSER_STATE.md).

A distributable archive still requires the owner's unique bundle identifier,
Apple signing team, certificates, and profiles. Those settings are intentionally
not committed.
