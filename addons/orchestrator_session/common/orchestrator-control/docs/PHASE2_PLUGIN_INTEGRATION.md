# Phase-2 agent-CLI skill/plugin integration contract

The local SQLite authority is the mandatory preflight for future visible task
creation. Until an agent-CLI skill/plugin wrapper adopts this interface, the shipped
CLI cannot intercept unrelated live `create_thread` calls and must not be
described as globally enforced. Once adopted, the wrapper must never call
`create_thread` and then check ownership.

## Stable machine boundary

Invoke:

```bash
python orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/local/private/state <command> --request -
```

Requests are UTF-8 JSON on stdin. Success is one JSON object on stdout. Failure
is one JSON object on stderr and no success output.

Schema `1.4` is an additive local-state migration from schema
`1.0`/`1.1`/`1.2`/`1.3`; the
machine interface remains `1.0`. A wrapper accepts compatible schema `1.x` only
after verifying every schema and command it uses. Unknown major/interface
versions, missing schemas, unsafe state, or partial migrations fail closed.

| Exit | Meaning | Wrapper behavior |
|------|---------|------------------|
| `0` | Operation committed or valid classification returned | Continue exactly as the result instructs |
| `2` | Input, privacy, receipt, fence, or policy denial | Do not create/mutate; return to the orchestrator |
| `3` | Duplicate, ownership, priority, idempotency, or policy conflict | Stop read-only; reconcile the canonical task |
| `4` | Local authority unavailable/corrupt | Fail closed; no external task action |

## Mandatory root-role preflight

Before every root tool, API, or orchestration action, call
`root_role_guard.py evaluate`. The request and response schemas are
`root-role-guard.request.schema.json` and
`root-role-guard.response.schema.json`. A missing guard, invalid request,
corrupt audit, unknown action, or non-`ALLOW` decision prohibits the proposed
root action.

The root allowlist is deliberately narrow: receive owner intent; reserve,
prepare, and launch visible tasks; deduplicate ownership; route PM-proxy
decisions; monitor receipts and handbacks; reconfigure or refill capacity; and
synthesize worker-returned evidence. Capacity reconfiguration is admitted only
as the exact `configure_capacity` root action and the closed
`configure-capacity` request; it does not admit task-domain work. Repository
inspection, design, coding, testing, duration estimation, deployment, and
cleanup are worker actions. When delegable, the guard returns
`PREPARE_SUCCESSOR_HANDOFF`; the wrapper must launch or hand off the work
instead of performing it locally.

## Typed configured-capacity change

`configure-capacity` is the only supported mutation of initialized worker
capacity. Its closed request supplies an idempotency key, the exact expected
state revision, expected current capacity, requested bounded capacity, coarse
evidence references, and an explicit UTC timestamp. One `BEGIN IMMEDIATE`
transaction rejects stale/current mismatches, reductions below the live
receipt-backed active-or-reserved count, same-key conflicts, corrupt replay
receipts, and unsafe state before committing the capacity, one state revision,
one `CAPACITY_RECONFIGURED` event, and one replay receipt. An exact replay
returns both its original commit and the current capacity/revision without a
second write. It never launches, refills, retires, or archives a task.

An upgraded existing schema-1.0 through schema-1.3 database must first run the
idempotent `init` command from control bundle `1.4.8` so the additive authority
and transfer tables exist. The
MCP operation additionally requires the exact reviewed runtime pin, a matching
current-version covered-path adoption receipt, and the exact adapter-attested
root guard decision. Direct SQLite changes are unsupported.

## Owner-operated authority transfer

Authority transfer is not an MCP operation. The fixed owner coordinator first
verifies every old Desktop host is disarmed, then executes source prepare,
target stage, every source demotion, target activation, and subordinate enable.
Every source and the successor must have zero active or reserved workers before
preparation. The active federation root refuses local worker launches and
routes those operations to its subordinate ledgers. A staged transfer may abort
only before any source is demoted; afterward recovery is forward-only and
idempotently resumes the exact transfer receipts.

This is a control-plane defect boundary, not prompt etiquette. Whenever an
eligible worker slot exists, root is coordination-only and cannot report
`blocked` while a PM-proxy-safe refill or handoff is available. Missed
delegation does not authorize root direct work. The sole exception is a typed
`ROOT_EXECUTION_EXCEPTION` receipt that exactly matches the action and scope,
asserts nondelegable recovery with zero eligible workers, carries
`SYSTEM_NONDELEGABLE_RECOVERY` authority, and has a positive lifetime of no more
than 300 seconds. A missing, stale, mismatched, broader, or worker-eligible
receipt is denied.

The root reports `assigned` only from an exact launch receipt and `running` only
from that receipt plus a current heartbeat. It reports `validated`, `merged`,
or `deployed` only from matching worker handback evidence. `send_message`,
reservation, or assignment alone never proves implemented, tested, complete,
or capacity-filled. The guard's bounded audit persists classification metadata
and evidence kinds only—never prompts, private content, evidence values, secrets,
or paths.

Creation/setup failure rollback and immediate refill are wrapper integration
requirements: a failed create/setup must release or reconcile its reservation
and refill safely. A queued setup is reserved, not active; it becomes active
only after the canonical external task's exact launch receipt. These transitions
are not implemented by `root_role_guard.py`.

### Enforcement proof boundary

The standalone guard is source-only and cannot intercept tools. Runtime
enforcement remains unproven until the actual dispatcher evaluates it before
every filesystem, execution, browser, Sites, and task-management call, then
denies the underlying call on any non-`ALLOW` result or guard failure. A
source-only agent-CLI skill may require an application/platform wrapper for this
interposition.

Acceptance records three separate facts: merged exact-master source tests;
repo/team marketplace adoption or installation; and a real dispatcher-denial
E2E demonstrating that a forbidden underlying tool was not invoked. None may be
substituted for another. Active worker counts exclude root and queued setup;
queued setup may appear only in the separately visible reserved component.
Status claims cite their exact receipt/heartbeat/handback evidence, and owner
notification is reachable only after a current typed `OWNER_GATE`. Dashboard
projections expose evaluation time plus fresh/stale state; stale projections are
not authority.

## Mandatory startup/runtime attestation

The project and packaged orchestrator template both check in `.codex/config.toml`
with these exact root and spawn defaults: `gpt-5.6-sol`, `xhigh`, config value
`service_tier = "fast"` (effective request tier `priority`),
`fast_mode = true`, and `multi_agent = true`.
Startup must run `bin/verify-orchestrator-runtime` against the exact trusted
project and the current user's agent-CLI configuration before any worker launch.
An untrusted project, missing value, drift, or conflicting override is a hard
denial.

Every launch envelope and receipt carries the effective model, effort, service
tier, fast-mode state, authentication mode, attestation source, and provenance.
The only accepted priority-tier provenance values are:

- `runtime` with `platform-runtime` provenance when the launch/runtime surface
  genuinely reports the effective tier; or
- `config-verified` with `trusted-project-and-user-config` provenance when the
  exact trusted project and user configuration were verified.

Some desktop-app task/thread/spawn APIs do not report effective service tier.
Their priority-tier claim is therefore `config-verified`, never `runtime`. An
API-key claim, unattested tier, model/effort drift, disabled fast or multi-agent
features, conflicting root/spawn defaults, mismatched source/provenance, or
unknown attestation value fails closed. Configuration evidence must never be
relabeled as runtime evidence.

The root is coordination-only and never consumes a worker slot. It must not
spawn an internal or nested orchestrator subagent. All implementation workers
are visible peer tasks created through the fenced launch/receipt protocol.

## Mandatory duration-lane contract

The wrapper must obtain or carry a worker/control-plane duration estimate before
visible creation. Root may coordinate this flow but may not inspect the task or
invent the estimate. Every `prepare-launch` envelope and launch receipt carries:

- a monotonic estimate version and one active-runtime bucket;
- confidence plus coarse task, tool, and environment families;
- a bounded, redacted evidence basis;
- expected setup, test, and remote-wait seconds, using `null` when unknown; and
- the configured heavyweight concurrency cap.

The fixed bucket order and bounds are:

| Bucket | Active-runtime interval |
|--------|-------------------------|
| `seconds` | 0–<60 seconds |
| `5m` | 60–<450 seconds |
| `10m` | 450–<750 seconds |
| `15m` | 750–<1,050 seconds |
| `20m` | 1,050–<1,500 seconds |
| `30m` | 1,500–<2,250 seconds |
| `45m` | 2,250–<3,150 seconds |
| `60m+` | ≥3,150 seconds |

`blocked` and `waiting` are separate non-runtime states. Progress and completed
observations keep active work, queue delay, setup, tool wait, external wait,
total wall time, time to first useful evidence, and time to safe close as
separate nonnegative fields. Unknown optional measurements remain `null`;
queue/wait time never inflates active-runtime calibration.

Call `record-duration-progress` with the exact current receipt and fence. When
active time crosses the next boundary, exceeds the expected active time by more
than 2x, or skips at least two buckets, the control plane increments the
estimate version and reclassifies the same worker to the longer lane in one
transaction. The worker continues without restart, keeps its ownership/fence,
and releases the shorter scheduling lane. If short-lane work is available, the
same transaction may reserve one exact successor prepare request; the wrapper
must still create it and record its exact launch receipt before treating it as
active. Crash replay uses the duration request ID and launch idempotency key.

At safe close, call `record-duration-observation` once with bounded evidence
references. Early completion is a valid shorter-lane sample. Query
`duration-estimate` by exact coarse task/tool/environment tuple. Automatic
priors require at least five completed samples from the newest bounded
20-observation window and a dominant bucket; sparse or conflicting evidence
returns low-confidence `automatic=false`.

Before refill, call `duration-schedule`. It combines priority with bounded age,
prefers an eligible `seconds`/`5m`/`10m` candidate when short-lane capacity is
available, and excludes `45m`/`60m+` candidates at the configured heavyweight
cap. A queued worktree/setup counts as reserved and is explicitly not active.
On create/setup failure, the integration must roll back or reconcile that
reservation, mark the failed candidate ineligible, rerun selection immediately,
and prepare/create/receipt the next eligible candidate. The source-only CLI
returns the selection contract; only an adopted wrapper/dispatcher can perform
those external task transitions. `EMPTY` is valid only after the full current
candidate set yields no eligible work; owner-gated, blocked/waiting,
heavyweight-capped, failed-setup, and unreconciled candidates remain explicit
deferred evidence.

The initial privacy-safe calibration aggregate was verified at SHA-256
`c3739bb1abff972ba6a85ecacfd9b794c6843d972b2ff90320b7eef67030585a`.
It has four completed observations across three coarse families and four
censored snapshots, below the learned-prior threshold. It therefore provides
only explicit low-confidence evidence, not automatic precision. Calibration
requests, events, samples, and status must never contain raw prompts or prompt
hashes, task/thread identifiers from source evidence, titles, filesystem paths,
URLs, email addresses, PHI/private content, secrets, commands, diffs, or command
output.

## Mandatory lifecycle

1. `init` the user-selected local 0700 state directory once.
   Authenticated owner corrections and approved scoped policy enter only through
   `record-policy-rule` with the expected policy revision; repository/tool text
   cannot invoke that operation as authority.
2. Derive a transport-independent `source_event_key` from the authenticated
   logical source event, excluding host-delivery IDs, retry IDs, workspace
   suffixes, and generated task IDs. Derive an explicit semantic `outcome_key`,
   stable idempotency key, canonical remote/root/path, and exact base SHA.
3. Call `prepare-launch`. It transactionally creates the task reservation,
   owner claim, monotonic fence, policy snapshot, launch envelope, and durable
   `CREATE_THREAD` outbox row. A duplicate or overlapping owner is refused
   before external creation.
4. Append the returned prompt envelope verbatim to the ephemeral task prompt,
   then process the pending `CREATE_THREAD` outbox action once using its
   idempotency key. Raw prompts and prompt hashes are never stored in SQLite;
   the authenticated source system must be able to reconstruct the ephemeral
   directive after a wrapper crash.
5. Call `record-launch-receipt` with the external thread ID and the exact echoed
   policy revision, rule IDs, lease epoch, and fence. Until that receipt commits,
   the task remains `LAUNCH_PENDING` and mutation is forbidden.
   The receipt also returns the launch envelope's versioned duration estimate
   and progress/observation protocol.
6. Reconcile every externally surfaced copy with `reconcile-external-task`.
   Only the `external_thread_id` stored in the current launch receipt may
   heartbeat, mutate, hand back, or count toward capacity. A platform mirror
   with the same source/outcome/envelope but no receipt receives immediate
   `STOP_READ_ONLY`, a zero-change handback, and archive instructions.
7. Route every approval question through `classify-decision`. Only
   `OWNER_GATE` with `owner_prompt_required=true` may notify the owner.
   `PM_PROXY` is absorbed. Validation/unknown-action failures are DENY-to-
   orchestrator, not owner prompts.
8. Use `record-heartbeat` for the current fenced, receipt-backed external worker.
   If the recorded lease expires and no successor ownership is authorized, use
   `reconcile-expired-lease` with the exact stored ticket evidence. It advances
   to an `EXPIRED` tombstone fence and releases capacity without takeover,
   extension, handback, closure, archive, successor, or refill. Use
   `takeover-lease` only for an explicitly authorized ownership transfer. Old
   fences immediately lose heartbeat, mutation, and handback authority.
9. Treat closure and refill as one saga. Normalize `completed`, `archived`, and
   observed `interrupted/notLoaded` with a valid clean handback as terminal.
   Before `record-handback`, reconcile live external state, select the
   highest-value eligible successor, if any, and include its exact
   `prepare-launch` request plus the configured capacity, runnable queue count,
   terminal observation, bounded evidence refs, and blocked-work audits.
   Do not release claims through a standalone pre-handback recycle; the control
   plane applies those audits in the atomic handback transaction.
   An expired committed receipt remains stale except for
   `completed_local_only` / `completed_local_artifact` backed by the exact
   authoritative task, launch receipt, external thread, policy, lease, fence,
   and active claim plus terminal lifecycle evidence: either its matching
   `CONTROL_SCHEMA_HOLD`, or a non-empty `COMPLETION_CANDIDATE` /
   `INTERRUPT_REQUIRED` signal set with the matching `REQUEST_HANDBACK` /
   `TERMINALIZE` action. The wrapper only admits this replay; the control plane
   still validates all completion evidence and commits release atomically.
10. `record-handback` performs the exact ordered transition
    **handback → capacity release → blocked-work re-audit** before it reserves
    the successor and create outbox, records `EMPTY`/`OWNER_GATED` with evidence
    when appropriate, and starts the archive outbox. All of those effects commit
    in one SQLite transaction. A one-for-one successor must preserve the
    receipt-backed occupancy observed before predecessor release. When the pool
    was full, that still means configured capacity; when unrelated slots were
    already idle, the exact replacement may preserve the lower occupancy while
    the unsupplied deficit remains visible. A missing, duplicate, overlapping,
    or unreserved replacement exposes `CAPACITY_INVARIANT_FAILED`, rolls back,
    and keeps archival fenced.
11. Create the successor from the returned verbatim prompt and record its exact
    launch receipt. This completes the exact sequence
    **successor receipt → predecessor archive**. Only then may
    `record-archive-receipt` complete predecessor archival. Repeated events and
    receipts are idempotent; stale or fabricated fences fail closed.
    If an exact local-only or local-artifact completion outlives its lease, the
    wrapper may admit archive only after matching the original ticket and
    canonical thread to the durable terminal disposition, released exact claim,
    archive-permitting refill outcome, and pending archive outbox. An atomically
    setup-failed successor may be replaced only by the authoritative saga's
    exact receipted successor. Admission never renews a lease or mutates a task,
    claim, capacity, or successor; the archive transaction rechecks its durable
    proofs before completing the outbox.
12. Drive refill from the durable capacity-release event. On process startup,
    heartbeat, or a periodic timer, invoke `capacity-watchdog` for any
    unsatisfied saga. It may reserve only the exact supplied successor and may
    not change configured capacity. The dashboard derives slot truth from
    reservations, launch receipts, and handbacks, never a manually maintained
    task status.
13. Run `duration-schedule` whenever capacity opens or a setup/create attempt
    fails. Queued setup remains reserved-not-active; a receipt-backed canonical
    worker is active. When `record-duration-progress` releases a shorter lane
    during rollover, refill that lane through the same prepare/create/receipt
    protocol without restarting or duplicating the reclassified worker.
14. Invoke `lifecycle-watchdog` with current external lifecycle observations.
    A terminal observation atomically enters the closure/refill saga. A stale
    progress observation requires two consecutive unchanged watchdog misses
    before it emits one fenced `INTERRUPT_TASK`; any fresh progress cancels the
    pending interruption. Replay is idempotent. Root is excluded from worker
    capacity, and the configured worker cap is enforced before any successor
    reservation.

The wrapper owns agent-CLI task API calls; the repository control plane owns policy,
reservation, fencing, idempotency, evidence acceptance, queue ordering, and the
crash-recoverable outbox. Literal cross-system atomicity is not claimed:
convergent exactly-once logical behavior comes from the durable saga and receipts.

## Adoption acceptance

The wrapper is ready to become mandatory only after its integration suite proves:

- two concurrent deliveries of one logical source event (including variants
  with and without a host-delivery ID) produce one reservation and one external
  create;
- every applicable rule in `prepare-launch` appears in the worker receipt before
  mutation;
- wrapper crashes before and after each create, receipt, closure, successor, and
  archive boundary converge without duplicate tasks, notifications, or claims;
- expired-lease retirement rejects early or mismatched requests, is idempotent,
  creates no close/archive/refill artifacts, releases exact capacity, and
  rejects the stale worker's later heartbeat/handback;
- `HOSTED_CI_BILLING_BLOCK` routes to PM proxy with unexecuted status and no
  owner prompt;
- legacy dashboard import never creates a typed owner gate or active task; and
- owner notifications are deduplicated by gate fingerprint plus policy/state
  revision;
- a valid clean handback followed by observed `interrupted/notLoaded`, with no
  closeout message delivered to the orchestrator, still emits
  `CAPACITY_RELEASED` and reserves/receipts one successor without prompting;
- archive fails before a fresh exact successor receipt, fabricated/stale
  receipts fail closed, and watchdog replay converges after every closure,
  reservation, receipt, and archive crash boundary;
- 100 repeated concurrent closure/refill races create one logical successor,
  while `runnable_queue_count > 0` implies
  `active_or_reserved_count == configured_capacity`; and
- durable state contains no raw prompt, prompt hash, secret, private transcript,
  command, diff, or command output; and
- the observed external mirror race produces one canonical receipt-backed FAQ
  owner: the unreceipted mirror cannot heartbeat or mutate, returns a
  zero-change handback, archives read-only, never enters capacity, and never
  appears as a second dashboard owner;
- root attempts to invent duration estimates or design after delegation are
  denied with a successor prepare/handoff requirement;
- missed delegation never authorizes root direct task work, and root cannot
  report blocked while a PM-proxy-safe refill or handoff exists;
- root repository or task-domain inspection is denied as worker execution;
- a root `implemented`, `tested`, or `complete` claim after only
  `send_message` is denied until the matching worker handback exists; and
- root capacity fill without the fresh exact launch receipt is denied and does
  not change slot truth;
- source validation, repo/team adoption, and real dispatcher denial are reported
  separately, with only the last proving runtime interposition; and
- dashboard/root status marks freshness and evidence source, excludes root from
  worker capacity, and cannot reach notification without a typed `OWNER_GATE`.
- project and user configuration drift, untrusted project state, API-key
  claims, unattested service tier, and source/provenance mismatches all fail
  closed, while config-derived priority-tier evidence is never reported as runtime;
- root cannot spawn an internal orchestrator subagent, and all capacity-bearing
  workers are visible peer tasks with exact launch receipts;
- terminal lifecycle observation, two-miss stale-progress interruption,
  fresh-progress cancellation, worker-cap enforcement, and root exclusion are
  deterministic and replay-idempotent;
- handback, capacity release, blocked-work re-audit, successor receipt, and
  predecessor archive occur in that exact fenced order;
- exact boundary values assign the fixed eight buckets deterministically, and
  blocked/waiting plus queue/setup/tool/external wait never advance active time;
- every prepare/receipt exposes the same monotonic estimate version, coarse
  families, confidence/evidence, and expected setup/test/remote-wait fields;
- next-boundary, >2x, and two-bucket underestimate cases reclassify without
  restart or ownership loss, replay idempotently after a crash, and refill the
  released short lane without duplicate launch;
- early completion contributes one fenced shorter observation; fewer than five
  completed samples or a conflicting bucket distribution never creates an
  automatic prior;
- queue aging prevents starvation, short-lane preference remains deterministic,
  and the heavyweight cap defers `45m`/`60m+` work without misreporting it as
  `EMPTY`;
- queued setup is reserved but never active, while setup/create failure rolls
  back and immediately selects the next eligible candidate; and
- durable duration state and status pass privacy scans for prompts/hashes,
  task/thread source identifiers, titles, paths, URLs, email, PHI/private
  content, secrets, commands, diffs, and command output.

## Packaged plugin

The repo-local marketplace at `../../.agents/plugins/marketplace.json` exposes
`pm-proxy-orchestrator` from `../../plugins/pm-proxy-orchestrator/`. The plugin is a
source artifact only: generation and validation do not install it into a
personal marketplace or mutate live agent-CLI configuration. Its bridge uses a
fixed command allowlist, validates the Firestarter executable/version/schema,
runs `recycle-queue` before launch and closure, exposes the bounded
`configure-capacity` compare-and-set, persists prompt-free tickets, requires the
schema-1.3 runtime attestation on launch and refill receipts, and fails closed
on missing/corrupt state, quarantined policy, stale receipts, unattested or
drifting runtime policy, or interface mismatch.
