# Plan: remove the private launch-ticket file from the create path

Status: **design only, not implemented.** This change needs a control schema
bump, new control commands, a new host-adapter RPC, and rewritten hook data
sources. That is a schema/interface/version migration too broad to land as a
safe patch now, and any partial slice weakens a live protection (see the last
section). So this file is the code seam, not code.

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
- **Host adapter (`desktop_host_adapter.py`):** a new attestation-socket RPC
  (protocol interface 1.1 -> 1.2) so the adapter, which already answers
  ROOT/WORKER per `session_id` at `1702-1713`, also vouches the runtime
  attestation for a `commit-launch-receipt` bound to the attested root instance.
  The attestation must not come from a model-visible field; today
  `record-launch-receipt` takes it as a request field validated against the pin,
  and PostToolUse has no attestation authority, so the adapter is the only
  non-spoofable source.
- **PostToolUse hook (`post_tool_use_lifecycle.py`):** observe the `create_thread`
  tool call. It must now read `tool_use_id` (today it reads only
  `session_id/tool_name/tool_input/tool_response`, `447-480`, and never handles
  create) and `tool_response.external_thread_id`, correlate them with the
  PreToolUse admission on `(outbox_id, tool_use_id)`, and call
  `commit-launch-receipt` with the adapter-vouched attestation.
- **PreToolUse hook (`pre_tool_use_root_guard.py`):** replace the ticket-file glob
  (`matching_launch`, `active_admission_keys`, `fresh_unreceipted`,
  `archive_ready`) with a bounded read query to the control plane for
  pending-admission and receipt state, keeping the 5s timeout and fail-closed
  behavior.
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
- `hooks/pre_tool_use_root_guard.py`, `hooks/post_tool_use_lifecycle.py`,
  `hooks/host_attestation.py`: data-source change, create observation in
  PostToolUse, attestation vouching.

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
