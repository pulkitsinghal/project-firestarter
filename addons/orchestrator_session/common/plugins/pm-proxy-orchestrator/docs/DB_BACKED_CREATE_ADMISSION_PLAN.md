# Plan: remove the private launch-ticket file from the create path

Status: **design only, not implemented. Determination: the smallest complete
vertical slice is NOT safely supportable in one task without partial security
semantics** (reasoned in "Determination and bounded decomposition" below). This
change needs a control schema bump, two new control commands, two new
host-adapter RPCs, a new adapter-vouched attestation provenance primitive, and
rewritten PreToolUse/PostToolUse create handling. So this file is the code seam
and the bounded order to land it later, not code. Nothing here is implemented;
no gate is weakened and no dead code is landed.

This is independent of the landed doctor diagnostic (commit `ab2a17a`), which
is the near-term artifact for the live blocker. Ticket removal is **not** the
live repair: the live Codex blocker is pre-ticket (supported doctor/status
returns `state-fail-closed` on state access, before any `create_thread`). This
plan only re-homes an on-disk artifact; it does nothing for a state-access
fault and must be sequenced after that fault is diagnosed and cleared.

## What the ticket file does today, and where

The on-disk `{ticket_id}.ticket.json` (and refill's `refill-{task_id}.ticket.json`,
`refill_saga.py:236-268`) is a **bridge-side** artifact. The control CLI never
writes it; it only reads legacy tickets in reconciliation. It carries three jobs:

1. **One-shot create admission.** Written O_EXCL at
   `pm_proxy_bridge.py:935-949` (`write_ticket_new`, guard `ensure_ticket_parent`
   `928-932` raises `TICKET_EXISTS`). This file existence is the per-launch
   one-shot on the create path.
2. **Fence/receipt carrier** between MCP calls. Shape at
   `pm_proxy_bridge.py:2274-2296`: `policy_snapshot_revision`, `lease_epoch`,
   `fencing_token`, `applicable_rule_ids`, `outbox{outbox_id,kind}`,
   `owner_claim_id`, `receipt_deadline`, `runtime_policy`, and `receipt`
   (set at `record-launch-receipt`, `pm_proxy_bridge.py:2334-2338`, holding
   `external_thread_id` + `runtime_attestation`). The prompt is never in it
   (`contract.md:54`).
3. **Hook data source.** PreToolUse `matching_launch`
   (`pre_tool_use_root_guard.py:246-279`) matches the verbatim `create_thread`
   prompt envelope to a fresh unreceipted ticket and keys the one-shot admission
   ledger on `create:{outbox_id}` + the event `tool_use_id`
   (`admit_once` `382-428`, create path `509-526`). PostToolUse
   `classify_identities` (`post_tool_use_lifecycle.py:125-182`) globs
   `*.ticket.json` and reads `receipt.external_thread_id` to classify thread
   identity and clear lifecycle debt.

Every field the ticket carries already exists durably in the control DB:
`tasks` + `owner_claims` + `outbox(CREATE_THREAD)` + `launches.envelope_json`
/ `launches.receipt_json`. The CLI reconstructs identity from those rows and
never needs the file. The only create-path behavior with no in-DB analog is the
O_EXCL one-shot; the nearest in-DB patterns are `configure-capacity`'s
`expected_state_revision` compare-and-set (`orchestrator_control.py:2486-2499`)
and `record_setup_failure`'s `expected_outbox_id` compare + guarded poison
(`orchestrator_control.py:5078-5097`, `5156-5162`).

## Target seam

- **Control (new, additive at schema 1.5):**
  - `admit-create`: a compare-and-set that admits exactly one create against the
    current pending `outbox(CREATE_THREAD)` row for the task and a caller-supplied
    admission token (the `tool_use_id`), recorded in a new `create_admissions`
    table keyed `(outbox_id PRIMARY KEY, tool_use_id, admitted_at, state)`.
    Replay with the same token is an idempotent no-op; replay with a different
    token is denied (`CREATE_ADMISSION_REPLAY`), mirroring `admit_once`
    semantics but in the authoritative DB under one `BEGIN IMMEDIATE`.
  - `commit-launch-receipt`: the PostToolUse commit path. It takes the admitted
    `outbox_id`, the `tool_use_id`, the observed `external_thread_id`, and a
    runtime attestation vouched by the adapter (below). It performs the existing
    `launch_receipt` transition (`LAUNCH_PENDING -> RUNNING`, bind
    `external_thread_id`, persist `launches.receipt_json`, complete the
    CREATE_THREAD outbox) at `orchestrator_control.py:3269-3298`, but gated on a
    matching admission row instead of an orchestrator-supplied ticket.
- **Host adapter (`desktop_host_adapter.py`), attestation-socket protocol 1.1 ->
  1.2, two new RPCs.** The hooks never touch the DB or run the control CLI
  directly for the create path; they call the adapter, the only non-model-visible
  authority:
  - `admit_create` (served by the adapter's `AttestationServer`): PreToolUse
    calls it for a covered `create_thread`, passing the `outbox_id` (parsed from
    the verbatim launch envelope in the prompt) and the event `tool_use_id`. The
    adapter verifies the caller is the attested ROOT session
    (`session_id == root_thread_id`, `desktop_host_adapter.py:1708`) for this
    exact instance, then invokes the control `admit-create` command, which runs a
    `BEGIN IMMEDIATE` compare-and-set against the current pending
    `outbox(CREATE_THREAD)` row keyed on `(outbox_id, tool_use_id)`: first writer
    wins and is recorded in `create_admissions`; a replay with the same
    `tool_use_id` is an idempotent `ADMITTED`; a replay with a different
    `tool_use_id` is denied `CREATE_ADMISSION_REPLAY`. The adapter returns
    ADMIT/DENY to the hook.
  - `commit_launch_receipt` (served by the adapter): PostToolUse calls it after a
    successful `create_thread`, passing the same `tool_use_id` and the observed
    `external_thread_id`. The adapter vouches a runtime attestation from
    non-model-visible state (next section) and invokes control
    `commit-launch-receipt`, which fences `LAUNCH_PENDING -> RUNNING`, binds the
    external thread, and persists the launch receipt, gated on the matching
    `create_admissions` row.
- **PostToolUse hook (`post_tool_use_lifecycle.py`).** It must now observe the
  `create_thread` call (today it handles only observation and lifecycle tools,
  `447-480`, and never reads `tool_use_id`): read `tool_use_id` and the stable
  `external_thread_id` from `tool_response`, and call the adapter
  `commit_launch_receipt` RPC with exactly those. It never computes or supplies
  the attestation itself and never writes the receipt directly.
- **PreToolUse hook (`pre_tool_use_root_guard.py`).** It must NOT be reduced to a
  bounded read. The authoritative one-shot admission moves into the control DB:
  the hook calls the adapter `admit_create` RPC, which performs the authoritative
  `BEGIN IMMEDIATE` CAS. The hook keeps its verbatim-prompt envelope match (to
  derive `outbox_id`), its 5s timeout, and fail-closed behavior, but it no longer
  owns the one-shot (the DB CAS does); a missing, duplicate, or different-token
  admission is denied by control, not by a local file or a local read.
- **MCP + bridge:** `prepare_launch`/`record_launch_receipt` stop writing the
  ticket on the new path; the bridge retains legacy ticket read/write behind a
  version gate so in-flight legacy tickets still reconcile.

Invariants preserved, and how:
- **Exact root attestation:** adapter socket ROOT/WORKER by `session_id`
  (`desktop_host_adapter.py:1708`) unchanged; the new commit RPC rides it.
- **Fresh reservation/deadline:** `receipt_deadline` becomes a column on
  `create_admissions`; staleness is checked in `commit-launch-receipt`.
- **Policy revision / lease epoch / fencing token:** still enforced by
  `checked_task` (`4151-4173`) on the commit transition.
- **One-shot replay denial:** the `create_admissions(outbox_id)` PK + token
  compare replaces the O_EXCL file; the authoritative one-shot moves into the DB.
- **Prompt non-persistence:** no change; the prompt is still never stored
  (`contract.md:54`).
- **Fail-closed adapter loss:** unchanged inside the isolated host
  (`DESKTOP_HOST_ADAPTER.md:16-18`); the new RPC fails closed on socket loss.
- **Crash recovery / created-but-unreceipted stays read-only:** still enforced
  by `require_external_receipt` (`4176-4198`, `launches.receipt_json IS NULL`
  -> `EXTERNAL_RECEIPT_REQUIRED`). A created worker whose receipt was never
  committed remains non-mutating exactly as today.
- **Heartbeat/handback/archive untouched** until their ticket reads are replaced
  by equally authoritative control queries.

## Adapter attestation vouching (exact mechanism)

`commit-launch-receipt` must accept a runtime attestation only when it provably
originated from the adapter, bound to the attested root and this exact create,
never from a model-visible or worker-supplied field. The mechanism extends the
existing host-attested, consume-before-dispatch bootstrap grant
(`validate_bootstrap_grant` / `consume_bootstrap_grant` in `mcp_server.py`) to
bind the create parameters:

1. **Non-model-visible source.** The adapter derives the attestation values
   (root/worker model, reasoning effort, service tier, fast_mode,
   `service_tier_attestation`, `tier_provenance`, `auth_mode`, `history_mode`,
   `parent_attestation_present`) from the pinned runtime policy
   (`runtime-pin.json`, mode 0600) and its own launch configuration, both held
   only in owner-only files and the adapter process. None come from the hook
   event, the prompt, the tool input or result, or any model-reachable field.
2. **Attested-root binding.** The adapter serves the RPC from its
   `AttestationServer`, which decides ROOT vs WORKER by
   `session_id == root_thread_id` (`desktop_host_adapter.py:1708`) and carries the
   private `instance_id` from `session.json`. The commit is refused unless the
   calling session is the attested ROOT for this exact instance.
3. **Create-parameter binding.** The adapter loads the `create_admissions` row it
   admitted (keyed `outbox_id + tool_use_id`) and refuses to vouch unless the
   commit's `outbox_id`, `tool_use_id`, `task_id`, fence identity
   (`policy_snapshot_revision`, `lease_epoch`, `fencing_token`), and
   `external_thread_id` match that admission and the task's current pending
   CREATE_THREAD outbox and fence.
4. **Provenance to control.** The adapter emits a one-use attestation grant whose
   `binding_sha256` canonically covers `{instance_id, root_thread_id, outbox_id,
   task_id, tool_use_id, external_thread_id, runtime_attestation, plugin_version,
   plugin_tree_sha256, runtime_sha256, source_commit_sha, base_sha, issued_at,
   expires_at, nonce}`. Control validates the binding, re-resolves host
   attestation (decision ROOT, control_grant PROMPT_FREE, matching instance_id)
   exactly as the control-schema-hold path does, consumes the grant before
   dispatch in a private revocation ledger (so a replay is a revoked-grant
   denial), and only then performs the fenced commit. A model-supplied or forged
   attestation has no valid consumed grant and is denied.
5. **Fail-closed.** Socket loss, a disarmed or expired session, a binding or
   host-attestation mismatch, a revoked or already-consumed grant, or an expired
   `receipt_deadline` all deny the commit; the created worker stays read-only
   through `require_external_receipt` (`launches.receipt_json IS NULL`).

## Determination and bounded decomposition

**Determination for this task: do not implement.** The smallest complete
vertical slice cannot be landed in one task without partial security semantics.
The decisive reason is step 4: the adapter-to-control attestation provenance is a
new bootstrap-grant-class primitive, newly bound to the create parameters, that
has to be designed, implemented, and adversarially proven non-spoofable to the
confidence this fail-closed plane demands. The existing bootstrap grant took
several hardening releases to reach that bar; a create-bound variant cannot reach
it in one pass. The surrounding slice (schema 1.5, two commands, an adapter
protocol bump, two hook rewrites, a dual path, and the full adversarial matrix
across control + adapter + hooks) compounds the risk, and any subset either
weakens a gate or lands code that is unwired on the live create path.

The bounded order to land it later, each step independently testable and never
leaving a half-open create path (legacy ticket admission stays authoritative
until D5 cuts over):

- **D1** Additive schema 1.5: `create_admissions` table + connect-time migration
  + `SCHEMA_VERSION` bump + bridge `SUPPORTED_SCHEMA_VERSIONS` += "1.5". Legacy
  1.4 stays fully functional. Ships only with the release that re-pins, since any
  control-bundle change invalidates the runtime pin and adoption.
- **D2** Control `admit-create` (the `BEGIN IMMEDIATE` CAS) + schemas + MCP typed
  tool, proven at the control layer (CAS, idempotence, replay, concurrency).
- **D3** Control `commit-launch-receipt` + schemas + the attestation-grant
  provenance primitive, with its OWN adversarial proof (forged and model-supplied
  denial, consume-before-dispatch, revocation, create-parameter binding) before
  any hook or adapter calls it.
- **D4** Adapter protocol 1.2 `admit_create` + `commit_launch_receipt` RPCs +
  attestation derivation/vouching, with a live adapter fence test.
- **D5** PreToolUse calls `admit_create`; PostToolUse observes `create_thread` and
  calls `commit_launch_receipt`. The PostToolUse payload canary (proving
  `tool_use_id` and stable `external_thread_id` extraction) is a prerequisite.
- **D6** Dual-path cutover behind the version gate: the DB path becomes
  authoritative only after adoption and canary; legacy ticket writing is removed
  last. Heartbeat/handback/archive move off ticket reads only once their
  replacements are equally authoritative.

D1 and D2 must not land alone on the live tree: a schema bump with no consumer
invalidates the pin for no behavior, and a command unwired to the create path is
dead until D5. So this is the future sequencing for a dedicated release, not a
slice to begin now.

## Affected modules

- `orchestrator-control/orchestrator_control.py`: `SCHEMA_VERSION` 1.4 -> 1.5;
  `SCHEMA_SQL` new `create_admissions` table; a connect-time `migrate_*` gated on
  installed version (pattern at `1254-1295`); two new command handlers + parser
  entries + request validators; init gate at `1364-1373` stays major-only.
- `orchestrator-control/schemas/`: new `admit-create.request/response` and
  `commit-launch-receipt.request/response` schema JSON, with `$id` suffixes the
  bridge checks.
- `skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py`:
  `SUPPORTED_SCHEMA_VERSIONS` += "1.5"; a `schema_at_least((1,5))` schema set in
  `validate_installation`/`doctor`; dual-path create (legacy ticket retained).
- `skills/pm-proxy-orchestrator/scripts/refill_saga.py`: refill create path moves
  to the admission RPC; legacy refill tickets retained during migration.
- `scripts/mcp_server.py`: new typed tools for the admission + commit commands,
  routed with the same request-file discipline; dual-path.
- `scripts/desktop_host_adapter.py`: new socket RPC + protocol version bump;
  `PROMPT_FREE_CONTROL_TOOLS` add the new tools (task creation itself stays
  outside the grant per `DESKTOP_HOST_ADAPTER.md:40-42`).
- `hooks/pre_tool_use_root_guard.py`: call the adapter `admit_create` RPC for
  covered `create_thread` (no local one-shot; the control CAS owns it), keeping
  the verbatim-envelope match, 5s timeout, and fail-closed behavior.
- `hooks/post_tool_use_lifecycle.py`: observe `create_thread`, extract
  `tool_use_id` + stable `external_thread_id`, call the adapter
  `commit_launch_receipt` RPC; never supply the attestation itself.
- `hooks/host_attestation.py` + `desktop_host_adapter.py`: socket protocol 1.1 ->
  1.2 for the two RPCs and the attestation vouching above.

## Transaction and state-machine changes

- New `create_admissions` row written in the same transaction family as
  `reserve_launch` or a dedicated CAS, one-shot by PK, replay-denied by token
  mismatch.
- The `LAUNCH_PENDING -> RUNNING` transition and CREATE_THREAD outbox completion
  are unchanged in effect; only their trigger moves from the ticket-driven
  `record-launch-receipt` to the admission-gated `commit-launch-receipt`.
- The state machine itself (`TASK_STATES`) is unchanged; no new states.

## Migration / version requirements

- Control schema 1.4 -> 1.5 (additive): bump, add table, add connect-time
  migration, and keep init major-only so existing 1.4 DBs upgrade in place.
- Bridge: add "1.5" to `SUPPORTED_SCHEMA_VERSIONS` and the per-minor schema-file
  set; add the new schema JSON; keep legacy ticket code paths.
- `INTERFACE_VERSION` can stay 1.0 (new commands are additive to the wire
  contract); the **adapter attestation socket** interface bumps 1.1 -> 1.2 for
  the new RPC; `TICKET_VERSION` stays for legacy tickets.
- Any control-bundle content change invalidates the runtime pin and the
  dispatcher adoption; shipping requires a fresh pin and re-adoption and a
  canary. Those are owner/deploy steps and are out of scope for this branch.
- Dual-path runs until the DB-admission path is equally authoritative and
  adopted; only then are legacy ticket writes removed.

## Adversarial test matrix

- Replay a create with the same `tool_use_id` (idempotent no-op) and with a
  different `tool_use_id` (denied `CREATE_ADMISSION_REPLAY`).
- Admit against a stale/poisoned/completed outbox (denied).
- Commit with a mismatched fence (`STALE_FENCE`), mismatched external id
  (`EXTERNAL_RECEIPT_MISMATCH`), or after `receipt_deadline` (denied).
- Commit with a worker-supplied (unvouched) attestation (denied; must come via
  the adapter).
- Adapter socket absent/corrupt/disarmed during admit or commit (fail closed,
  worker stays read-only).
- Crash between admit and commit: worker reserved, `launches.receipt_json` NULL,
  mutation blocked (`EXTERNAL_RECEIPT_REQUIRED`); re-commit idempotent.
- Crash between commit and outbox completion: replay completes without a second
  receipt.
- Legacy ticket present (migration) still reconciles and archives.
- Two concurrent admits for the same outbox: exactly one wins (PK), the other
  denied; no double capacity.
- Prompt never written to the admission row or any log.
- Hostile tool_response (forged external id, extra fields) does not bind a
  receipt that the admission did not authorize.

## Why a smaller change weakens protections

- Adding the control admission command alone (no hook/adapter rewrite) is dead
  code that still requires a schema bump (invalidating the pin) and does not
  remove the file; the hooks still depend on the file, so nothing is actually
  re-homed. That is the first third of the migration, i.e. the partial
  implementation to avoid.
- Removing the O_EXCL ticket without the DB one-shot removes the per-launch
  one-shot admission, re-opening create replay.
- Teaching PostToolUse to commit without the adapter-vouched attestation lets a
  worker self-attest its own receipt, collapsing the root/runtime fence.
- Changing the create path without the PreToolUse data-source rewrite either
  leaves the file in place (goal unmet) or strips the hook's admission input
  (fail-open create).
- Touching heartbeat/handback/archive before their reads are equally
  authoritative breaks the receipt chain mid-migration.

## State separation (as of this writing)

- **Diagnostic patch state:** `ab2a17a` on this branch, tested, committed, not
  pushed.
- **New code/test state for this plan:** none. This is a design document only.
- **Runtime state:** untouched. No deploy, pin, adoption, restart, SQLite edit,
  install, or other-project change.
