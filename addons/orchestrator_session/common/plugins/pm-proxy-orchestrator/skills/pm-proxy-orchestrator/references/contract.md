# Firestarter control-plane boundary

Pinned source contract:

- Firestarter commit: `ac60826b4dbb8622f56732538f44edfecb690eac`
- Current-master integration base:
  `a32741d7958eeff7fd49ccd979c44acccdc69d91`
- Compatible CLI versions: `1.x`
- Compatible ledger schemas: `1.0`, `1.1`, `1.2`
- Machine interface: `1.0`
- Canonical document:
  `addons/orchestrator_session/common/orchestrator-control/docs/PHASE2_PLUGIN_INTEGRATION.md`

Invoke only:

```text
python /absolute/orchestrator_control.py \
  --state-dir /absolute/private/state COMMAND --request -
```

The wrapper permits these commands: `init`, `status`, `record-policy-rule`,
`effective-rules`, `prepare-launch`, `record-launch-receipt`,
`classify-decision`, `record-heartbeat`, `takeover-lease`,
`record-handback`, `record-archive-receipt`, `recycle-queue`, capacity
reconciliation, schema 1.2 duration commands, and `record-setup-failure`.
`root-action` invokes the
fixed adjacent `root_role_guard.py`, not an arbitrary caller command.

Exit meanings:

- `0`: committed or valid result; continue exactly as instructed.
- `2`: schema, privacy, receipt, fence, or policy denial; do not create/mutate.
- `3`: duplicate, ownership, priority, idempotency, or policy conflict; stop
  read-only and reconcile the canonical task.
- `4`: local authority unavailable, locked past its bounded timeout, corrupt, or
  incompatible; fail closed.

Every successful response must contain exactly one UTF-8 JSON object on stdout,
with `interface_version: "1.0"`, `ok: true`, the expected operation, and an
object result. A failed command must produce one error JSON object on stderr and
no success output.

The launch ticket is a private local transport receipt, not authority. Ticket
1.2 includes the task/claim identity, control schema, privacy-safe duration
estimate, policy revision, applicable rule IDs, lease epoch, fencing token,
outbox ID, timestamps, and external receipt state. Legacy 1.0 tickets are
migrated in memory on read and rewritten on the next safe mutation. A ticket
must never contain or hash the prompt. Firestarter's SQLite ledger and current
fence remain authoritative.

The visible task prompt must be the exact `prompt` returned by `prepare-launch`.
The prompt is ephemeral and must not be copied into logs, tickets, dashboards,
or handbacks.

Response validation intentionally fails on:

- unsupported CLI major or missing required 1.0 schema files;
- a non-1.0 machine response;
- malformed, extra, or missing launch receipt fields;
- any quarantined rule in status;
- an owner-gate response without `owner_prompt_required: true`;
- a PM-proxy response with `owner_prompt_required: true`;
- a receipt ticket older than five minutes before external receipt commit;
- a ticket without a committed receipt before heartbeat or handback.
- an external task ID other than the exact ID in the current launch receipt;
- schema 1.2 without its duration and root-role schemas or guard script;
- a direct terminal handback that bypasses `close-and-refill`.

## Closure/refill extension

The plugin adds a local durable saga without changing Firestarter interface
`1.0`. `close-and-refill` normalizes `completed`, `archived`, and
`interrupted/notLoaded` observations only when the structured handback is clean.
It records `CAPACITY_RELEASED`, calls `recycle-queue`, derives active/reserved
slots from Firestarter task receipts and reservations, and reserves the
highest-priority candidate. Predecessor archive remains blocked until reserved
successors have exact launch receipts or the saga records a terminal empty,
owner-gated, or already-full outcome with evidence.

Exact replay of a close/refill or successor receipt is idempotent and never
creates another reservation. Replay returns durable saga state without
persisting or reconstructing a launch prompt; an unreceipted reservation must be
reconciled against the existing outbox/ticket.

`slot-status` is the dashboard source of truth. `watchdog-refill` is the
event-loss/periodic-heartbeat fallback. Both fail when runnable work exists and
active-or-reserved slots are below configured capacity.

## Root and duration adoption boundary

The root-role guard defines truthful statuses (`assigned`, `running`,
`validated`, `merged`, `deployed`) and their required receipt/worker evidence.
The supplied dispatcher calls that guard before protected tool callables and
proves denied calls have an underlying count of zero. It is not a global hook.

Schema 1.2 duration progress and observation are bound to the same external
receipt as heartbeat and handback. `duration-schedule` can exclude a failed
setup and choose the next eligible candidate without an owner prompt. Platform
rollback and task creation still require an adopted host transaction; absent
that integration the plugin reports the selected contract and fails closed.
