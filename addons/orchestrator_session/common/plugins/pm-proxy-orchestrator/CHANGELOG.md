# Changelog

## Unreleased

- Allow only exact authoritative terminal evidence to carry an expired
  committed receipt through `close-and-refill`: either an active matching
  `CONTROL_SCHEMA_HOLD`, or a completion-signalled `COMPLETION_CANDIDATE` /
  `INTERRUPT_REQUIRED` lifecycle with its matching required action. Admit both
  local completion dispositions to authoritative control validation, and keep
  recycle/release effects behind the atomic handback commit.

## 0.4.2 - 2026-08-04

- Add truthful `completed_local_only` and `completed_local_artifact` closure
  routes with exact provenance, hosted-CI/deployment truth, content-verified
  privacy-safe SHA-256 manifests, rollback/cleanup evidence, and strict replay.
- Add receipt-fenced control-schema holds, expired-unreceipted setup-failure
  poisoning, and exact one-claim release without generic repair authority.
- Route only typed owner decisions to one pinned private sink with exact
  receipt, source/request replay, recursion, privacy, and no-sink-authority
  protections. PM-proxy decisions return automatically and verified owner-gate
  decisions pass through unchanged.
- Bind the single hold-recovery operation to a short-lived, one-use private
  desktop bootstrap grant. Other task-domain, owner-gated, and generic control
  paths remain outside the prompt-free grant.
- Stop and join both stdio forwarding threads before proxy shutdown, including
  when stdin remains open after the child exits, so Python cannot abort while a
  daemon reader still owns a buffered-stream lock during interpreter cleanup.

## 0.4.0 - 2026-08-03

- Add schema-1.4 owner-operated leadership transfer: two or more drained roots
  prepare immutable receipts, one empty successor stages them, every source is
  demoted before the successor activates, and the sources are then enabled as
  separate subordinate capacity shards. The federation root cannot launch into
  its own ledger, source hosts must be disarmed, and all transfer steps are
  idempotent and crash-resumable.
- Preserve each subordinate's configured capacity so two four-lane shards
  report federated capacity eight without a direct `4→8` mutation. Policy and
  PM-proxy decisions remain rooted in the sole active federation root.
- Replace the Desktop stdio proxy's fixed-size `copyfileobj` reads with
  partial-read forwarding and per-frame flushes. Add a long-lived-pipe
  regression proving a small JSON-RPC initialize frame crosses before EOF.

## 0.3.6 - 2026-08-03

- Add a covered-root-only typed capacity compare-and-set with explicit expected
  capacity and state revision, bounds of 1–64, an active/reserved floor,
  conflict-safe replay, and one transactional capacity/revision/audit commit.
  Direct SQLite edits, uncovered callers, workers, and universal authority stay
  outside the operation.
- Add exact 4-to-8 activation, eight-lane concurrent-reservation ceiling,
  receipt-derived status, 8-to-6 rollback, and 8-to-4 rollback coverage and
  operator instructions.

## 0.3.5 - 2026-08-03

- Pass the private Electron data directory as an explicit Desktop command-line
  switch before macOS single-instance selection, removing the need for an
  owner-local launcher shim while retaining the environment value for Desktop's
  application-level configuration.
- Record and observe the exact isolation switch together with the Desktop,
  proxy, and app-server PIDs. Missing or prefix-colliding isolation, absent proxy
  observation, invalid private state, and startup/log failures disarm the host
  before returning an error.
- Keep the adapter session and launch capability in owner-only files and the
  parent environment, strip them before the real app-server, and use the exact
  `Popen` child handle for failed-start termination. Normal Desktop processes do
  not carry the private isolation switch and are never shutdown targets.
- Bind a prompt-free Desktop grant to the current-version covered-path adoption,
  verified runtime pin, private host proof, exact root task, and thirteen named
  typed control-plane tools. The isolated app-server receives only per-tool
  `approval_mode="approve"` overrides; attested workers are denied those tools,
  expired-lease reconciliation still prompts, and shell, file, browser, Sites,
  credentials, destructive, owner-gated, and universal paths remain outside the
  grant.

## 0.3.4 - 2026-08-03

- Add an opt-in Codex Desktop app-server proxy that binds root enforcement to
  one exact owner-selected thread ID instead of exporting a process-wide root
  role to root and worker tasks alike.
- Route native pre/post hook identity checks through an owner-private local
  attestation socket; exact root calls retain the existing guard, other thread
  IDs remain workers, and adapter loss fails closed inside only the isolated
  ORC desktop host.
- Require a fresh no-side-effect live hook proof, current runtime pin, exact
  typed MCP surface, content hashes, private state, and a capability-bound
  session before launch. Strip the launch capability before the real app-server
  starts and reject all non-app-server use of the adapter.
- Keep the normal desktop app and global Codex configuration unchanged. The
  bounded stop path disarms before signaling exact recorded processes and never
  force-kills or searches by process name.
- Require the enabled plugin's reported local source and exact versioned cache
  to match byte-for-byte with identical executable status, and preserve the
  adapter's executable bit in every generated stack.

## 0.3.3 - 2026-08-02

- Add an owner-private, content-addressed Firestarter runtime pin covering the
  control CLI, version, schemas, root-role guard, and runtime verifier.
- Allow typed MCP calls to omit `project_root` after pinning while rejecting an
  explicit mismatched root or any later runtime-bundle drift.
- Keep bootstrap doctor/status and expired-lease repair available, but deny new
  launch, close/refill, and watchdog-refill mutations until the current plugin
  version has both a verified runtime pin and covered-path adoption proof.
- Report exact automatic-control readiness as `DISABLED` or
  `COVERED_PATH_ONLY`; universal platform enforcement remains false.
- Remove dispatcher-adoption self-approval from the MCP surface. Only the
  owner-operated fixed bridge can record a live adoption receipt; status keeps
  unattended and universal automatic control false.

## 0.3.2 - 2026-08-02

- Add an exact ticket-derived expired-lease reconciliation tool that advances
  to a tombstone fence, marks only the stale owner claim expired, releases
  logical capacity, and proves that it created no handback, closure, archive,
  successor, or refill.
- Accept an explicit status clock and report reconciled leases as `EXPIRED`,
  while keeping plugin hooks a voluntary covered-path guardrail rather than
  claiming universal dispatcher enforcement.

## 0.3.1 - 2026-08-01

- Allow a fenced terminal handback to reserve an exact one-for-one successor
  while the receipt-backed worker pool is already below configured capacity.
  The closure transaction must preserve pre-release occupancy; missing,
  duplicate, overlapping, or unfenced successors still roll back atomically.
- Mark an exact reserved candidate as no longer runnable, transition its
  capacity saga on its own canonical receipt instead of unrelated global slot
  occupancy, and keep genuinely unsupplied idle slots visible.

- Add PM bridge/ticket 1.3 for exact root/worker runtime policy and launch
  attestation, including truthful `runtime` versus desktop-app
  `config-verified` priority-tier provenance and fail-closed API-key/drift handling.
- Accept Firestarter schema 1.3 lifecycle-watchdog contracts and preserve the
  receipt-fenced handback → release → blocked re-audit → successor receipt or
  terminal proof → archive sequence.
- Make root coordination-only with visible peer workers, no internal subagents,
  and root excluded from configured worker capacity.
- Add a local stdio MCP control surface so an enforced root can run only typed
  verifier, doctor, launch/receipt, heartbeat, lifecycle, close/refill, status,
  and archive-receipt operations without a general shell or filesystem tool.
- Gate covered task creation on one fresh exact ticket, gate archive on a
  satisfied refill saga, and add a PostToolUse lifecycle-debt fence that blocks
  repeat reads/waits and status/refill/archive actions until the exact worker's
  lifecycle watchdog succeeds.
- Bind the bundled MCP server explicitly through the plugin manifest, prohibit
  overlay-level root-hook activation, and document two-phase adoption plus
  owner-controlled recovery so hooks cannot silently precede reservation tools.
- Bound both hook lock waits, record lifecycle debt before observations,
  reject unsafe lock files, prune only terminal admission records, and prevent
  archive readmission after its receipt so stale state cannot hang or exhaust
  the dispatcher.
- Keep the closed dispatcher-adoption schema aligned with the exact 0.3.1
  plugin version, admit only the MCP registry's exact typed tool names, and
  clear lifecycle debt only from the documented successful result wrapper.

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
