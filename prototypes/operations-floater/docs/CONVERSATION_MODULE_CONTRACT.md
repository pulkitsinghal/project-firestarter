# Conversation module contract 1.0

Operations Floater owns the conversation UI, microphone permission, on-device
transcription, optional local speech output, ephemeral transcript, and the
single active conversation floor. A module never supplies UI and is never
dynamically loaded. Eligibility comes only from the app's compiled static
allowlist.

The machine-readable closed envelope is
[`conversation-module-contract-1.0.schema.json`](conversation-module-contract-1.0.schema.json).
Unknown fields fail closed.

## Fixed IPC

- Base URL: `http://127.0.0.1:11510/v1/conversation-modules`
- Health: `GET /{moduleID}/health`
- Turn, revoke, and end: `POST /{moduleID}/turn`
- Client header: `X-Client-App: operations-floater`
- Transport: ephemeral URL session, no cache, cookies, credentials, redirects,
  authentication headers, discovery, or alternate host.
- Limits: health 16,384 bytes; response 65,536 bytes; health timeout 2 seconds;
  turn timeout 10 seconds.

The allowlisted geometry adapter is:

- module ID: `example.verbal-orders.synthetic-geometry-recorder`
- provenance source: `example.project-verbal-orders.geometry-recorder`
- transcript providers: `onDevice`, `syntheticFixture`
- window binding: `verbal-orders.synthetic.geometry-canvas`

The selected-window relative-coordinate adapter is:

- module ID: `example.verbal-orders.relative-xy-recorder`
- provenance source: `example.project-verbal-orders.relative-xy-recorder`
- transcript providers: `onDevice`, `syntheticFixture`
- generic wire binding: `verbal-orders.neutral.selected-window`
- events: normalized mouse move/down/up/drag, normalized scroll plus bounded
  deltas, and all keyboard down/up/modifier changes as key code, modifier flags,
  and elapsed timing

Any visible window may be selected. Application names are UI hints only and
are not an allowlist. The actual process ID, window ID, title, and bundle
identity are absent from the wire request and reviewed artifact; the host keeps
the exact process/window binding in memory only to reject cross-window events.

The built-in checkpoint reference additionally permits `typed-keyboard`.
The geometry recorder does not, so the typed composer is disabled while it has
the floor.

## Bounds

| Field | Bound |
|---|---:|
| narration | 2,000 characters |
| context | 6 turns, 1,000 characters each, 6,000 total |
| normalized events | 32 |
| allowlisted window bindings per manifest | 8 |
| window width and height | 100 through 8,192 |
| reply | 4,000 characters |
| question | one, 600 characters |
| statuses | 4; summary 240 characters |
| checkpoints | 8; summary 400 characters |
| proposed actions | 4; title 120 characters |

Event sequences start at one and are contiguous within each request. Pointer
coordinates are normalized to `0...1`. Navigation keys are closed to Tab,
Return, Space, arrows, and Delete. Escape is intentionally absent because the
host always reserves it for returning to the dashboard.

The relative XY module additionally admits raw hardware key codes, modifiers,
key phase, mouse button, scroll deltas, and elapsed milliseconds. It does not
recover characters. Pointer and scroll events must be within the selected
topmost window; keyboard events require that same selected window to be active.

## Floor and transaction semantics

The host creates a fresh `floor_<lowercase UUID>` token after a ready health
response and pins the returned 64-character lowercase SHA-256 provenance
digest. One module may have the floor. Request sequence starts at one and
increments only after a fully validated, non-refused response.

Every response must echo the contract version, module, request, turn, sequence,
floor grant, and pinned provenance exactly. A refusal, provider omission,
provider mismatch, floor mismatch, sequence gap or replay, binding drift,
provenance drift, malformed or oversized envelope, unknown field, or
out-of-capability value fails closed. The host attempts a revoke and always
clears its local floor. The module must restore its exact pre-turn snapshot on
failure.

Revoke and end use the same token with `state: revoked`, carry no narration,
context, events, or window, and clear ephemeral module state. Their required
`transcriptProvider` field is control-envelope metadata and is not checked
against the turn-provider allowlist.

## Privacy and actions

Every accepted manifest has exactly this privacy posture:

- `ephemeralOnly: true`
- module microphone, UI, TTS, arbitrary network, persistence, screen capture,
  input injection, and executable replay: `false`

The synthetic recorder receives only bounded narration, closed normalized
events, and an allowlisted neutral synthetic window binding. The relative XY
recorder receives only bounded narration, selected-window normalized input
events, key codes, modifiers, and timing. It may return calibrated
checkpoints, at most one question, statuses, and proposals. Every proposed
action must set `humanApprovalRequired: true`; executable replay is not part of
this contract.

The host's voice mode is off by default. Start is explicit and may trigger the
macOS Microphone and Speech Recognition prompts. Production transcription sets
`requiresOnDeviceRecognition = true` and fails closed if provider metadata or
on-device support is unavailable. Spoken replies are separately default-off,
local, and interruptible. Each non-empty transcript update appears immediately
as a pending human chat turn and auto-submits after exactly 2.000 seconds
without another update, whether or not the recognition provider emits its
optional final-result signal. A visible linear countdown covers that exact
window and resets when speech resumes. Human and assistant bubbles show their
local creation time beside the sender attribution. Pause, stop, floor revoke,
module switch, clear, and teardown cancel the staged turn. Transcript/session
memory is in-memory only and is cleared on stop, disable, revoke, or app exit.

Dashboard Router replies are labeled only from bounded Router-reported
`responder.kind` or `responder.provider` metadata. The accepted identities are
Claude, Codex, and local-LLM. The host does not infer identity from a model
string; missing, malformed, or other identity metadata rejects the reply.
