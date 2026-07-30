# Changelog

## Unreleased

- Add PM bridge/ticket 1.3 for exact root/worker runtime policy and launch
  attestation, including truthful `runtime` versus desktop-app
  `config-verified` priority-tier provenance and fail-closed API-key/drift handling.
- Accept Firestarter schema 1.3 lifecycle-watchdog contracts and preserve the
  receipt-fenced handback → release → blocked re-audit → successor receipt or
  terminal proof → archive sequence.
- Make root coordination-only with visible peer workers, no internal subagents,
  and root excluded from configured worker capacity.

## 0.3.0 - 2026-07-28

- Accept Firestarter ledger schemas 1.0 through 1.2 while preserving interface
  1.0 and the pinned ac608 compatibility test; require capacity features at
  1.1 and duration/root-guard contracts at 1.2.
- Migrate legacy 1.0 tickets in memory to ticket 1.2 and write new tickets with
  the control schema, owner claim, and privacy-safe duration receipt.
- Add a host-adoption dispatcher adapter that calls `root_role_guard.py` before
  filesystem, exec, browser, Sites, or task tools, with an end-to-end denial
  test proving zero underlying calls.
- Reject direct terminal handback outside `close-and-refill`; make closure and
  successor receipt retries idempotent without persisting launch prompts.
- Fence heartbeat, handback, and duration reclassification to the exact
  receipt-backed external task; cover both observed external mirror races.
- Expose schema 1.2 duration scheduling, progress, observation, and estimation
  commands. Failed setup candidates are excluded and the next eligible lane is
  selected, but platform reservation rollback/dispatch still requires host
  adoption.
- Add a privacy-safe resource scheduler that keeps logical lane capacity
  separate from CPU/process oversubscription, permits light parallel work, and
  serializes same-contention-group heavyweight work.
- Bundle the supported default `PreToolUse` hook as a
  `COVERED_PATH_GUARDRAIL`; document trust, hosted-path, opt-out, write-stdin,
  and non-spoofable caller-identity gaps plus the unexecuted live E2E plan.
- Bridge schema 1.2 `record-setup-failure` with an exact unreceipted ticket so
  Firestarter can atomically poison the failed create, release its claim, and
  reserve the next eligible successor without owner prompting.

## 0.2.0 - 2026-07-28

- Interoperate with Firestarter schema 1.1 native capacity sagas while retaining
  interface 1.0 and pinned schema 1.0 compatibility.
- Carry normalized terminal observation, capacity, queue count, and evidence
  into native `record-handback` when available.
- Keep archive fenced until all selected successors have fresh exact receipts,
  with local watchdog recovery and durable EMPTY/OWNER_GATED evidence.
- Bind worker mutation and capacity to the canonical external task ID recorded
  in the launch receipt; mirrored external tasks receive immediate read-only
  stop, zero-change handback, and archive instructions.

## 0.1.0 - 2026-07-28

- Add the fail-closed Firestarter `1.0` bridge and operational agent-CLI skill.
- Require queue recycling and `prepare-launch` before visible task creation.
- Add exact rule/fence tickets, receipt and heartbeat guards, typed decision
  routing, sanitized policy recording, and fenced handback/archive flows.
- Add deterministic unit, integration, privacy, adversarial, concurrency, and
  pinned-Firestarter acceptance tests.
- Add a receipt-derived closure/refill saga, exact terminal-status normalization,
  capacity invariant dashboard, event-driven refill, and watchdog fallback.
- Add repo-local marketplace, install/update/rollback, security, integration,
  and retain/remove documentation.
