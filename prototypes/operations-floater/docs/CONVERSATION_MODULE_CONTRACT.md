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

## Built-in reference module

The only module in the compiled allowlist is the deterministic synthetic
checkpoint reference used for contract testing:

- module ID: `firestarter.synthetic.checkpoint`
- display name: `Synthetic checkpoint reference`
- provenance source: `firestarter.operations-floater.synthetic`
- transcript providers: `typed-keyboard`, `onDevice`, `syntheticFixture`

It exercises the full envelope — narration, bounded context, statuses,
checkpoints, and human-approval-gated proposed actions — without capturing any
real content. Additional modules would each be added to the compiled allowlist
with their own manifest, provenance, and privacy posture; none is bundled here.

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

## Capability vocabulary

A manifest declares a bounded capability set (see the schema `capabilities`
enum): `narration`, `checkpoints`, `proposed-actions`, and an optional bounded
input-context vocabulary of `normalized-pointer-events`, `navigation-keys`,
`raw-keyboard-events`, `scroll-events`, `placeholder-events`, and
`neutral-window-context`.

Event sequences start at one and are contiguous within each request. Pointer
coordinates are normalized to `0...1`. Navigation keys are closed to Tab,
Return, Space, arrows, and Delete. Escape is intentionally absent because the
host always reserves it for returning to the dashboard. Input-context events are
bounded metadata only: key codes, modifier flags, and elapsed timing are carried
but printable characters are never reconstructed. Any window binding a manifest
uses must appear in its own `allowedWindowBindingIDs` allowlist; unlisted
bindings fail closed.

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

A module receives only bounded narration, closed normalized events, and an
allowlisted window binding. It may return calibrated checkpoints, at most one
question, statuses, and proposals. Every proposed action must set
`humanApprovalRequired: true`; executable replay is not part of this contract.

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
