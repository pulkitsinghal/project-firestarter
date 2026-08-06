# Operations

Use an absolute compatible Firestarter CLI and an already selected private state
directory. The examples below use placeholders intentionally.

For MCP operation, first pin the exact reviewed runtime from the installed
plugin root:

```bash
python3 scripts/configure_runtime_pin.py \
  --project-root /absolute/clean/firestarter-runtime
```

The MCP server validates that private content pin on every call. Once pinned,
`project_root` is optional; supplying a different root is denied. Doctor,
status, and exact expired-lease repair remain available before pinning for
bootstrap/recovery, but prepare-launch, close-and-refill, and watchdog-refill
also require a matching current-version covered-path adoption receipt.

Dispatcher adoption is an owner operation, not an MCP tool. After the complete
live covered-path canary passes, leave root-role execution and use the fixed
bridge command with an owner-reviewed schema-valid request file:

```bash
python skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py \
  --cli /absolute/firestarter/orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/orchestrator-state \
  record-dispatcher-adoption \
  --request /absolute/private/dispatcher-adoption.json
```

The MCP server consumes the resulting receipt for readiness but cannot create
or replace it. Status may enable only
`covered_path_automatic_launch_refill_allowed`; it always reports
`unattended_automatic_launch_refill_allowed: false` and universal enforcement
false.

Before a root action, call `root-action`. An adopting runtime must route every
filesystem, exec, browser, Sites, and task tool through
`dispatcher_adapter.py`; on `DENY`, it must not invoke the underlying tool.
This is mechanically tested with a synthetic dispatcher, but calls outside the
adopted dispatcher remain outside that adapter. The bundled `PreToolUse` hook
adds a `COVERED_PATH_GUARDRAIL` after trusted installation; it is not universal.

```bash
python skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py \
  --cli /absolute/firestarter/orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/orchestrator-state \
  doctor
```

Initialize a new state directory only after the operator selects it and sets mode
`0700`:

```bash
python skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py \
  --cli /absolute/firestarter/orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/orchestrator-state \
  init --now 2026-07-28T22:00:00Z
```

After updating an existing schema-1.0 through schema-1.3 state to control bundle
`1.4.7`, run the same idempotent `init` command once before recreating the
runtime pin. It adds authority-transfer state and does not change stored
capacity. The bundle also repairs an early schema-1.4 hold table before status
or doctor reads without changing any accepted hold. Control `1.4.7` retains the
exact terminal archive proof checks, keeps state schema and capacity unchanged,
and accepts covered-dispatcher adoption from plugin `0.4.8`. That plugin repairs
only its private hook lifecycle ledger; it does not migrate SQLite authority.
Install the complete version-distinct plugin `0.4.8` before recreating the
runtime pin; do not
overwrite an older cache under the same version identity. Then read
`status` and capture its exact `revision` and
`worker_capacity.configured_capacity`. A capacity change is a separate typed
compare-and-set and never creates a worker:

```json
{
  "interface_version": "1.0",
  "request_id": "capacity-4-to-8-UNIQUE",
  "expected_state_revision": 123,
  "expected_configured_capacity": 4,
  "requested_configured_capacity": 8,
  "evidence_refs": ["owner-request-capacity-eight"],
  "now": "2026-08-03T22:00:00Z"
}
```

```bash
python skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py \
  --cli /absolute/firestarter/orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/orchestrator-state \
  configure-capacity --request /absolute/ephemeral/configure-capacity.json
```

This bridge form is the typed underlying CLI boundary for disposable validation;
it does not attest an agent caller and is not a live covered-path authorization
shortcut. The live desktop root calls the equivalent
`pm_proxy_configure_capacity` MCP operation. That covered path additionally
requires the exact runtime pin, current-version dispatcher adoption, private
adapter session, and exact root-role guard. Exit `2`, `3`, or `4` means no
capacity change and no subsequent launch. On exit `0`, verify the returned
previous/committed revisions and capacity with a fresh `status`; only then
prepare four additional workers independently. At the eight-lane ceiling,
exactly four additional reservations may succeed from a receipt-backed
four-lane starting state; a concurrent ninth reservation must fail
`CAPACITY_FULL`. Same-key exact replay is read-only;
same-key changed input is a conflict. Never edit SQLite or combine the capacity
change with a launch/refill request.

Before visible task creation, prepare complete `recycle-queue` and
`prepare-launch` request JSON files:

```bash
python skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py \
  --cli /absolute/firestarter/orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/orchestrator-state \
  prepare-launch \
  --recycle-request /absolute/ephemeral/recycle.json \
  --launch-request /absolute/ephemeral/launch.json \
  --ticket /absolute/private/orchestrator-state/task.ticket.json
```

Only exit `0` permits one external create. Send the returned `prompt` verbatim.
Then record the external ID before any task mutation:

```bash
python skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py \
  --cli /absolute/firestarter/orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/orchestrator-state \
  record-launch-receipt \
  --ticket /absolute/private/orchestrator-state/task.ticket.json \
  --external-thread-id EXTERNAL_TASK_ID \
  --runtime-attestation /absolute/ephemeral/launch-attestation.json \
  --request-id STABLE_RECEIPT_REQUEST_ID \
  --now 2026-07-28T22:01:00Z
```

The launch attestation reports the effective root/worker model and effort.
Use `service_tier_attestation: "runtime"` only when the platform genuinely
surfaces effective service tier. Some desktop-app task/thread and spawn APIs do
not, so an exact trusted project plus matching project/user configs uses
`config-verified` with `trusted-project-and-user-config`. Never call that
runtime evidence; API-key Fast semantics and unattested/conflicting provenance
are denied.

Call `heartbeat` with `--external-thread-id` before first mutation and
periodically. A mirror ID is denied before the Firestarter mutation command.
Use
`classify-decision` for every approval question.

When a ticket's stored lease has already expired and ownership must only be
retired, call `reconcile-expired-lease` with that ticket, a unique request ID,
and an explicit UTC clock. The bridge derives the task, claim, external receipt,
epoch, fence, and deadline from the ticket; it does not accept a replacement
payload and does not rewrite the ticket. A successful result must say
`EXPIRED`, `capacity_released: true`, and false for closure, archive, and refill.
It is not a takeover, extension, handback, or task-platform archive.

If the task platform surfaces any second task with the same delegated envelope,
call `reconcile-external-task` with its external ID. Only the ID recorded in the
ticket receipt may proceed. Apply the returned `STOP_READ_ONLY`,
`RETURN_ZERO_CHANGE_HANDBACK`, and `ARCHIVE_EXTERNAL_MIRROR` actions immediately;
the mirror is never a capacity slot.

For closure, call `refill_saga.py close-and-refill` with the receipt-bearing
predecessor ticket, structured handback, and refill request. The refill request
contains configured capacity, normalized terminal observation, owner-gated
evidence, and full candidate `prepare-launch` requests. Create every returned
successor exactly once and record each through `record-refill-receipt`.
Successor receipt also requires `--runtime-attestation`; do not inherit or
invent a tier claim merely because the predecessor was receipted.

If the receipt-backed pool was already below configured capacity, an exact
one-for-one successor preserves the occupancy observed before release rather
than pretending unrelated idle slots are filled. The selected candidate is no
longer runnable once atomically reserved; its own canonical receipt satisfies
the predecessor saga, while any genuinely unsupplied deficit remains visible.

Run `slot-status` for dashboard truth. Run `watchdog-refill` on startup and
periodic heartbeat as the fallback for lost closeout messages. Use
`record-archive-receipt` only after the refill saga permits archive and the
external archive succeeds.

For schema 1.3, run `lifecycle-watchdog` after each worker message, wait timeout,
and before every status claim. Objective completion evidence and fresh changed
remaining-work progress determine whether to request handback or terminalize.
An exact interrupt receipt performs release and blocked re-audit atomically;
archive remains fenced until the selected visible peer successor is receipted
or an evidenced terminal outcome exists. Root never spawns internal subagents
and never occupies worker capacity.

Schema 1.2 exposes `duration-estimate`, `duration-schedule`,
`record-duration-progress`, and `record-duration-observation`. The last two
require both a receipt-bearing ticket and the caller's exact external task ID.
`duration-schedule` excludes `setup_state: failed` candidates and selects the
next eligible candidate. For a Firestarter `LAUNCH_PENDING` task whose setup
failed before receipt, call `record-setup-failure` with its exact ticket and a
successor-ticket path. Firestarter atomically poisons the failed create outbox,
releases the claim, and may reserve the next candidate; the bridge returns the
successor prompt/ticket for one external create and exact receipt. Neither
operation can undo a reservation created by an unrelated platform. If the host
has not adopted rollback plus receipt-backed dispatch for that path, fail
closed.

`resource_scheduler.py` is a pure scheduling primitive for host contention. Its
privacy-safe profile contains only light/heavy class, a coarse contention-group
alias, and low/moderate/high CPU, memory, and I/O intensity. It keeps logical
lane occupancy separate from process oversubscription: light work can fill
parallel lanes, while same-group heavyweight work serializes. It does not start,
pause, stop, install, or deploy a process or service.

Do not save launch request files containing prompts in durable evidence. The
Firestarter source system must reconstruct them after a crash. Delete ephemeral
copies through the normal task-owned cleanup path after receipt.
