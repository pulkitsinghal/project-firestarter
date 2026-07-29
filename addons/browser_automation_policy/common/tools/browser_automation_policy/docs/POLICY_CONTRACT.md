# Browser automation policy contract

## Scope

Version 0.1 is a hermetic reference policy, not browser automation. It accepts
typed, content-minimized synthetic observations and can authorize a handoff to
a future executor. No observer, browser extension, input driver, executor,
network client, credential flow, screenshot/OCR path, or deployment is
included.

The design was informed by a 2026-07-28 public-source browser-automation
research checkpoint. That checkpoint was treated as untrusted design input:
the committed schemas, finite state, and adversarial tests in this package are
the shipped authority.

## Binding and invalidation

Every proposal and candidate is bound to:

`(tabId, documentId, frameIds, frameDocumentIds, frameGenerations, originIds,
documentGeneration, surfaceGeneration, adapterVersion)`.

A committed navigation, document replacement, frame detach/reattach, tab
reuse, adapter change, or surface-generation change invalidates old handles
and confirmations. Mutation notifications are wakeups only; observers must
re-resolve current state immediately before handoff.

The full origin and frame-origin chain must appear in the capability grant.
Cross-origin frames without the exact chain refuse. Opaque or inaccessible
frames must be represented as ungranted origin IDs; geometry cannot bypass the
refusal. Grants also enumerate exact `(adapter, action, effect, targetKind,
targetContractDigest)` tuples. The digest covers the full product-owned target
contract, so callers cannot relabel a destructive target, swap semantic and
Citrix identities, or substitute a geometry baseline.

## Typed actions and reconciliation

Each action has one effect class:

| Effect | Example actions | Confirmation | Required postcondition |
|---|---|---:|---|
| observe | observe, focus | 0 | `state-observed` |
| navigate | activate, navigate | 1 | `navigation-reconciled` |
| edit-draft | set/clear/select | 2 | `draft-reconciled` |
| external-submit | send, submit, upload | 3 | `external-effect-reconciled` |
| destructive | delete, permission grant | 3 | `destructive-effect-reconciled` |

Draft edits require a compatible typed reversal action and a bound reversal
payload digest. External and destructive effects must be declared irreversible
and cannot auto-retry. Confirmations bind the proposal and payload digests,
document ID, document/surface generations, tier, and expiry; the expiry tick
itself is stale. Prompt-injection signals raise the minimum confirmation to
tier 2 without granting the page any authority.

Preconditions are observed facts. Postconditions are reconciliation
obligations for a future executor. The policy never reports an effect as
completed.

`proposalDigest` is computed by the reference type from the canonical task,
typed action/effect/adapter, complete lifecycle binding, adapter-specific
target, payload digest, finite conditions, reversibility, and expiry. It is not
a caller-selected value. JSON integrations must recompute and compare this
digest before accepting a confirmation, ledger key, or handoff.

The in-memory reference ledger makes planning atomic within one process. A
future executor must use shared durable storage and atomically consume both the
handoff nonce and idempotency key. Handoffs expire at the earliest of proposal
expiry, grant expiry, or 60 ticks after issuance; authorization never means the
effect ran.

Relative XY proposals carry a `relative-region` target whose semantic identity,
trained regime, normalized bounds, and viewport/layout/transform generations
are part of both the target digest and proposal digest. The same fields are
carried in the handoff so a future executor can revalidate them. A separate
caller-selected drift baseline is not accepted.

## Deterministic refusals

`DecisionCode` is a closed enum. Important safety outcomes include:

- `document-changed`, `frame-changed`, `stale-handle`;
- `origin-not-allowed`, `frame-not-allowed`,
  `cross-origin-frame-blocked`, `target-not-allowed`;
- `target-ambiguous`, `target-hidden`, `target-disabled`,
  `target-unstable`, `target-obscured`, `shadow-root-closed`;
- `semantic-required`, `geometry-not-allowed`, `geometry-untrained`,
  `geometry-drift`;
- `confirmation-required`, `confirmation-stale`,
  `prompt-injection-review`;
- `action-replayed`, `idempotency-collision`,
  `prior-outcome-indeterminate`; and
- `remote-session-changed`, `remote-frame-stale`.

Unknown action/effect combinations fail as `intent-unsupported`. Unknown
schema fields are forbidden by the JSON contracts.

## Privacy-safe evidence

Decision evidence is reconstructed from a fixed allowlist. It contains the
policy/schema versions, decision code, allow/deny result, opaque proposal ID,
adapter, generation counters, frame depth, and confirmation tier. It has no
nested arbitrary data and is bounded to 1 KiB.

Synthetic fixtures are intentionally rich in state transitions but contain no
raw page prose, URLs, accounts, identifiers, screenshots, or private data.
