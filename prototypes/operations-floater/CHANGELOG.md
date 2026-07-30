# Operations Floater changelog

## 1.2.0 (build 3) — unreleased

- Add **Ember**, a dismissible, vector-drawn corner companion that mirrors the
  canonical snapshot: it naps when the queue is empty, focuses while lanes run,
  briefly celebrates when work reaches the finished lane, and shows concern on a
  verified failure, attention signal, or pending owner decision. Mood, pose,
  motion, and status text are deterministic and Reduce-Motion aware. The
  companion is drawn with SwiftUI Canvas and uses no image asset, camera,
  microphone, network service, analytics, or external transmission. Adds a
  headless `--render-companion-preview` mood-gallery still-frame.
- Add a switchable **companion style** (`CompanionStyle`) so the corner companion
  ships as either **Ember** (the fox-kit pet) or **Nova**, a warm, stylized
  human assistant. Nova is a second SwiftUI Canvas rendering driven by the exact
  same mood/pose/motion state machine — no behavioral change — mapping every mood
  to a distinct, Reduce-Motion-aware human expression (breathing/blinking idle,
  lean-in focused, warm open-grin celebrating, worried-brow concerned, eyes-closed
  sleeping). The choice persists via `AppStorage`
  (`OperationsFloater.CompanionStyleV1`) and switches live from the
  **Companion Style** app menu. Extends the headless preview with an optional
  `--companion-style` flag and adds a committed Nova mood-gallery still-frame.

- Add a local-only, read-only receipt-feed 1.1 source with strict shape,
  duplicate-key, provenance, file-type, size, and SHA-256 validation.
- Read content-addressed `current` first and use LKG only when current fails
  pointer, digest, JSON, schema, or provenance validation. A valid stale
  current feed remains visible with degraded freshness.
- Add native **NOW**, **DECISIONS**, and **RECENTLY DONE** mappings plus
  current/stale/LKG/offline provenance badges. Missing or invalid feed data
  degrades only this panel and never disables existing dashboard features.
- Pin the reviewed dashboard snapshot, LKG, feed schema, manifest schema, and
  sanitized manifest hashes. No raw prompt, private path, or private content
  enters the source or tests.
- Preserve Router chat/review, voice and floor control, Relative XY recording,
  race/resource/privacy panels, collapse persistence, keyboard behavior,
  nonactivating background tests, and truthful empty dashboard behavior.

## 1.1.0 (build 2) — unreleased

- Add a read-only signed-code identity preflight for first install and update.
  Updates must preserve the owner bundle identifier, pass signature and
  Gatekeeper validation, and satisfy installed/candidate designated
  requirements in both directions before replacement.
- Keep routine unsigned or ad-hoc builds disposable so they cannot silently
  replace the app instance that owns Input Monitoring permission.
- Keep routine validation bundle-free on the active macOS profile after
  confirming Xcode 26.5 still invokes `lsregister` when
  `REGISTER_WITH_LAUNCH_SERVICES=NO` is supplied.
- Enforce one recorder host with a process-scoped application lease while
  retaining the existing single-Space window policy and Dock launcher.
- Keep the `AppIcon` plist and asset-compiler declarations in the XcodeGen
  source of truth so regenerating the project cannot drop the Dock icon.
- Roll back floor ownership, selected-window recording, the global event
  monitor, and voice state when either half of **Give floor** fails to start.
- Reject unexpected embedded login items, agents, daemons, privileged helpers,
  or launch services in the current helper-free release shape.
- Add synthetic coverage for compatible and incompatible code identities,
  helper rejection, Input Monitoring refusal, voice startup failure, successful
  joint startup, and one-instance locking. The tests do not sign code, request
  TCC access, launch an installed app, or modify System Settings.
