# Local orchestrator control plane

This Python-stdlib companion enforces the machine-checkable parts of the
[`Orchestrator Bill of Rights`](../ORCHESTRATOR_BILL_OF_RIGHTS.md). It is a
prompt-safe boundary for a future Codex skill/plugin wrapper, not a network
service and not a replacement policy source.

## Authority and storage

- `policy-ledger.json` contains versioned generic rules with stable IDs,
  selectors, precedence, provenance, expiry/supersession, effects, and typed
  owner gates.
- `orchestrator_control.py` stores live authority in one local SQLite database
  using `BEGIN IMMEDIATE`, foreign keys, unique task identities, transactional
  owner claims, monotonic fences, and a durable create/archive outbox.
- `root_role_guard.py` is the mandatory pre-action boundary for the root
  orchestrator. It permits only control-plane actions, requires exact receipt
  or worker evidence where applicable, and denies task execution with a
  successor prepare/handoff requirement.
- The caller selects a local state directory. The CLI enforces directory mode
  `0700`, database mode `0600`, current-user ownership, and no symlink path
  components.
- Schema `1.2` migrates an existing schema `1.0` or `1.1` database in place by
  adding capacity-saga and duration-calibration state. The stable JSON interface
  remains `1.0`; copying an older database over a migrated database is not a
  supported rollback.
- Raw prompts are returned ephemerally to the wrapper and are not stored or
  hashed. Handback evidence is validated but only typed redacted summaries are
  retained. Legacy dashboard JSON is quarantined byte-for-byte for rollback and
  is never executable authority.
- There are no network calls, telemetry, third-party packages, arbitrary command
  fields, rule evaluation, or shell execution.

Initialize and inspect:

```bash
python orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/state init \
  --now 2026-07-28T18:00:00Z

python orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/state status
```

All request commands accept UTF-8 JSON through `--request FILE` or
`--request -`. The JSON schemas in [`schemas/`](schemas/) and the integration
contract in
[`docs/PHASE2_PLUGIN_INTEGRATION.md`](docs/PHASE2_PLUGIN_INTEGRATION.md) define
the stable `1.0` wrapper boundary.

## Duration-calibrated worker lanes

Each `prepare-launch` result carries a duration estimate and protocol. The
active-runtime buckets are exact half-open intervals:

| Bucket | Active seconds |
|--------|----------------|
| `seconds` | 0–<60 |
| `5m` | 60–<450 |
| `10m` | 450–<750 |
| `15m` | 750–<1,050 |
| `20m` | 1,050–<1,500 |
| `30m` | 1,500–<2,250 |
| `45m` | 2,250–<3,150 |
| `60m+` | ≥3,150 |

`blocked` and `waiting` are non-runtime states. The launch estimate includes a
monotonic estimate version, confidence, coarse task/tool/environment family,
bounded evidence basis, expected setup/test/remote-wait components, and the
heavyweight concurrency cap. A legacy request with no estimate receives a
low-confidence compatibility fallback; it does not create a learned prior.

`record-duration-progress` records active work separately from queue, setup,
tool wait, external wait, and total wall time, plus time to first useful
evidence and time to safe close. Optional unknown measurements remain JSON
`null`; they are not rewritten as zero. Crossing the next bucket boundary,
exceeding the estimate by more than 2x, or skipping two or more buckets
reclassifies the same fenced worker to a longer lane in one local transaction.
The worker is not restarted, ownership is preserved, the shorter lane is
released, the estimate version increases, and a bounded calibration event is
emitted. A supplied successor may be reserved in that same transaction to
refill the released short lane, but does not count as active until its exact
launch receipt exists.

`record-duration-observation` accepts one completed, receipt-backed observation
per task and records early finishes as shorter-lane evidence. `duration-estimate`
uses the newest 20 completed observations for an exact coarse
task-family/tool-family/environment-class tuple. Fewer than five completed
samples returns `SPARSE_EVIDENCE`; a non-dominant or tied distribution returns
`CONFLICTING_EVIDENCE`. Neither result permits an automatic prior.

`duration-schedule` applies priority plus bounded queue aging, protects
available `seconds`/`5m`/`10m` capacity from starvation, and caps concurrent
`45m`/`60m+` work. Queued setup is reserved but not active. Failed setup is
excluded as a rolled-back reservation so the caller can immediately run the
next selection and receipt-backed prepare/create flow. `EMPTY` is truthful only
when a capacity deficit exists and no candidate remains eligible; otherwise the
result is `SELECTED` or `CAPACITY_FULL`.

The seed calibration aggregate was verified at SHA-256
`c3739bb1abff972ba6a85ecacfd9b794c6843d972b2ff90320b7eef67030585a`.
It contains four completed observations across three coarse families and four
censored snapshots, so it is useful only as low-confidence evidence and cannot
enable an automatic learned prior. Its privacy assertions report no task/thread
identifiers, paths, prompts, URLs, email addresses, private content, PHI, or
secrets. Durable calibration state follows the same rule and stores no raw
prompt or prompt hash.

## Mandatory root-role preflight

Before every root tool call or action, the wrapper evaluates a bounded JSON
request:

```bash
python orchestrator-control/root_role_guard.py \
  --state-file /absolute/private/state/root-role-audit.json \
  --request - evaluate
```

The allowlist is limited to receiving owner intent; visible-task
reserve/prepare/launch; ownership deduplication; PM-proxy decision routing;
receipt/handback monitoring; capacity refill; and evidence synthesis. Repository
or task-domain inspection, design, implementation, testing, duration estimation,
deployment, cleanup, and unknown action types fail closed and require a
delegated successor.

This is enforced as a control-plane defect boundary, not as prompt etiquette.
While an eligible worker slot exists, root is coordination-only and cannot call
itself blocked if PM-proxy-safe refill or handoff is available. The sole
direct-task exception is an exact `ROOT_EXECUTION_EXCEPTION` receipt matching
the action and scope, asserting `eligible_worker_count=0` and nondelegable
recovery, carrying `SYSTEM_NONDELEGABLE_RECOVERY` authority, and expiring no
more than 300 seconds after issuance. Stale, scope/action-mismatched, broader,
or worker-eligible receipts are denied.

Visible launch requires a verified prepare authorization. Capacity refill may
count a successor only with its fresh exact launch receipt. Status synthesis is
also evidence-gated: `assigned` requires a launch receipt, `running` adds a
current heartbeat, and `validated`, `merged`, or `deployed` require the matching
worker handback evidence. A sent delegation message cannot prove implemented,
tested, or complete.

The optional audit file is capped at 256 rows and retains only action type,
classification, decision, reason, required action, truthful status, and verified
evidence kinds. It never retains request/action IDs, evidence values, prompts,
private content, secrets, or paths. Invalid input or corrupt audit state fails
closed.

Creation/setup rollback, automatic refill after setup failure, and the
distinction between a queued setup reservation and a receipt-backed active slot
remain wrapper/control-plane integration dependencies. This standalone guard
does not implement those state transitions and never treats a queued setup as
active.

## Runtime adoption and proof boundary

`root_role_guard.py` is a validated source boundary, not a tool interceptor.
Until the active Codex dispatcher calls it before every filesystem, process
execution, browser, Sites, and task-management tool and suppresses the
underlying call for denial, error, timeout, or unavailable state, adoption is
voluntary and runtime enforcement must not be claimed. A source-only skill may
need an application/platform wrapper to enforce this ordering.

Keep three acceptance stages distinct:

1. merged exact-master tests prove the guard and schemas are present and
   deterministic;
2. repo/team marketplace adoption or installation proves availability, not
   dispatcher interposition; and
3. a real dispatcher-denial E2E proves the prohibited underlying tool never ran.

Active worker capacity counts canonical receipt-backed workers only, never root
or a queued setup. The `active_or_reserved` projection may count queued setup
only in its separately visible reserved component. Status claims name their
receipt/heartbeat/handback source.
Owner-notification code is reachable only after a current typed `OWNER_GATE`
with `owner_prompt_required=true`. Dashboard projections must show their
evaluation time and a freshness/stale marker; stale rows do not prove slot or
completion truth.

## Stable commands

| Command | Contract |
|---------|----------|
| `record-policy-rule` | CAS a typed, scoped, privacy-safe learned rule into the live ledger with monotonic rule and policy revisions. |
| `prepare-launch` | Resolve and explain effective rules; reject duplicate source/outcome/idempotency or overlapping ownership; atomically reserve the task, claim, fence, envelope, and `CREATE_THREAD` outbox before external creation. |
| `effective-rules` | Show included and excluded rules with deterministic reason codes and precedence evidence. |
| `record-launch-receipt` | Require the exact policy/rule/fence echo and external task ID before state becomes `RUNNING`. |
| `reconcile-external-task` | Confirm the receipt-backed external task or return immediate `STOP_READ_ONLY`, zero-change handback, archive, and capacity-exclusion instructions for a platform-created mirror. |
| `classify-decision` | Return `PM_PROXY` or `OWNER_GATE`; unknown/unsafe input is denied to the orchestrator and zero-step hosted-CI billing blockage is unexecuted infrastructure, never an owner prompt. |
| `takeover-lease` | Advance lease epoch and fencing only after the active lease expires. |
| `record-heartbeat` | Extend only the current fenced owner lease; stale workers are rejected. |
| `record-handback` | Validate exact refs, typed checks, CI/deployment/privacy truth, owned resource disposition, and normalized terminal observation; atomically release capacity, reserve an optional successor, and durably start the fenced closure/refill saga. |
| `capacity-watchdog` | Reconcile a durable saga after an event loss or crash, optionally reserve one exact successor, and expose a visible deficit until receipt-derived capacity is satisfied. |
| `record-archive-receipt` | Complete the archive outbox idempotently only after the successor launch receipt or evidenced `EMPTY`, `OWNER_GATED`, or `CAPACITY_FULL` outcome. |
| `recycle-queue` | Audit every blocked item in one transaction and rank the highest-value safely resumable work before lower-value replenishment. |
| `record-duration-progress` | Record separated active/queue/setup/wait/wall timing and atomically reclassify an underestimated receipt-backed worker without restart or ownership loss. |
| `record-duration-observation` | Record one fenced completed timing sample, including early-finish evidence, without private task content. |
| `duration-estimate` | Return a bounded learned prior only after at least five consistent completed samples for the exact coarse family/tool/environment tuple. |
| `duration-schedule` | Select a fairly aged eligible lane, preserve short-task capacity, cap heavyweight work, and report queued/failed setup truth without dispatching by itself. |
| `migrate-decisions` | Dry-run or quarantine legacy `{generated,items}` board bytes; map `decide` to needs-classification and `play` to showcase/non-work without producing owner notifications or task authority. |
| `status` | Export a privacy-bounded local view of rules, canonical receipt-backed tasks, capacity, duration lanes/calibration, freshness, visible invariant failure, and outbox state. |

## Exit semantics

| Exit | Meaning |
|------|---------|
| `0` | Operation committed or valid read/classification returned. |
| `2` | Invalid schema/privacy/receipt/fence or denied unsafe action; do not mutate or create externally. |
| `3` | Duplicate, owner, priority, idempotency, lease, or policy conflict; stop read-only and reconcile. |
| `4` | State unavailable/corrupt or unexpected failure; fail closed. |

Success is one JSON object on stdout. Failure is one JSON object on stderr.
Tests cover 100-repeat prepare and closure/refill races, the observed
receiptless external FAQ mirror, event/watchdog recovery, the missed
`interrupted/notLoaded` closeout, archive fencing, crash rollback, stale fences,
rule conflict quarantine, CI truth, privacy, unsafe dashboard links, exact
bucket assignment, sparse/conflicting priors, waiting-time exclusion,
underestimate rollover, early finish, reclassification crash/race recovery,
fair scheduling/setup failure, and the root-role regressions for self-assigned
estimation/design, repository inspection, premature completion claims after
`send_message`, and receiptless capacity fill.
