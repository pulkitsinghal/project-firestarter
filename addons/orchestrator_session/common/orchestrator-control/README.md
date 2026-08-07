# Local orchestrator control plane

This Python-stdlib companion enforces the machine-checkable parts of the
[`Orchestrator Bill of Rights`](../ORCHESTRATOR_BILL_OF_RIGHTS.md). It is a
prompt-safe boundary for a future agent-CLI skill/plugin wrapper, not a network
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
- Control bundle `1.4.10` retains state schema `1.4` and migrates an existing
  schema `1.0` through `1.3` database in place. This patch adds truthful local
  closure, receipt-fenced schema holds, and exact setup-failure repair. It also
  repairs an early schema-1.4 control-schema-hold table by adding its two
  nullable release columns before any status or doctor read, preserving every
  existing row and authority record. Re-running `init` adds stable
  authority identity, transfer receipts, and federation membership without
  changing configured capacity. The stable JSON interface remains `1.0`;
copying an older database over a migrated database is not a supported
rollback.
- Control `1.4.10` adds one typed stale-present-ticket archive transaction. It
  requires an exact terminal `ARCHIVE_PENDING` task, released claim, current
  revision/policy/lease/fence identity, pending archive outbox, fresh independent
  archived/unavailable external proof, and one unique mode-`0600` non-symlink
  ticket whose inode and content match both the bridge proof and SQLite launch
  authority. Only failed-plus-`EMPTY`, superseded-plus-`EMPTY`, or a superseded
  predecessor with one exact receipted, completed, archived successor is
  admissible. The bridge unlinks the exact ticket only after the archive/outbox
  commit; exact replay is safe when cleanup already completed. No claim,
  capacity, successor, or unrelated ticket is mutated.
- Control `1.4.9` adds a compare-and-set legacy archive reconciliation for an
  exact terminal task whose claim is released and archive outbox remains pending.
  The wrapper must independently prove that the canonical external task is
  archived or unavailable and that a bounded private ticket scan found no old
  transport ticket. The transaction rechecks exact task/external identity,
  revision, fence, claim, lifecycle, launch receipt, and outbox; partial or unsafe
  authority fails closed and exact replay is idempotent. Actionable
  `capacity_failure` now reflects only the newest capacity audit while every
  historical audit row remains inspectable.
- Control `1.4.8` extends the transactional archive check to accept a receipted
  successor that has itself reached an exact terminal handback, released claim,
  completed lifecycle, and matching archive outbox. It extends covered-dispatcher
  adoption to plugin `0.4.9`. That plugin classifies
  lifecycle observations before recording worker debt and migrates only an
  exact non-task owner-decision sink after authoritative receipt proof. It also
  binds a stale wrapper ledger to the exact authoritative saga, failed
  reservation, poisoned create outbox, receipted replacement, terminal claim
  fence, and replacement archive state before an expired predecessor may reach
  the existing archive transaction. A `superseded` predecessor is eligible
  only when that authoritative replacement proof succeeds. An expired ordinary
  `completed` predecessor is admitted only through the same exact terminal
  ticket, handback, claim, refill, lifecycle, and outbox proof.
- Archive receipt now rechecks the committed terminal handback, released exact
  claim, archive-permitting capacity saga, canonical launch receipt, and one
  pending exact-thread `ARCHIVE_THREAD` outbox inside its transaction. Exact
  replay remains idempotent after the task and outbox are already complete.
- `completed_local_only` requires exact distinct base/candidate commits while
  structurally rejecting all delivery refs; `completed_local_artifact` requires
  exact base provenance plus a canonical bounded SHA-256 relative-path manifest
  whose current files match real create/modify/remove transitions. Both require
  literal unexecuted zero-step hosted CI, no external delivery/deployment, exact
  owner-claim cleanup, and an explicit EMPTY or owner-gated refill proof.
- `CONTROL_SCHEMA_HOLD` accepts only the exact decision, receipt, claim, epoch,
  fence, state/policy revisions, capacity, and replay target. It preserves the
  occupied lane and lifecycle evidence without accepting progress churn. The
  only release is the exact typed terminal handback.
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

## Single-leader federation

Schema 1.4 supports an owner-operated, forward-only authority transfer. Each
source must first have zero active or reserved workers. `prepare-authority-transfer`
freezes its ledger; `stage-federation` binds at least two exact source receipts
to an empty successor; `finalize-authority-transfer` demotes every old root;
`activate-federation` creates the sole active federation root; and
`enable-subordinate` reopens each preserved worker-capacity shard beneath it.

The federation root cannot launch workers into its own ledger. It coordinates
the subordinate ledgers, whose configured capacities remain separate. The
installed plugin's owner-only `federation_transfer.py` coordinator requires the
old Desktop hosts to be disarmed and resumes safely after a crash. The MCP
surface deliberately cannot prepare, accept, or activate its own authority.

## Audit-only adaptive capacity

[`adaptive_capacity_policy.py`](adaptive_capacity_policy.py) evaluates one
closed, caller-supplied metrics snapshot and returns a deterministic advisory
cap. It creates no reservation, performs no enforcement, collects no host
metrics, and authorizes no service action. Its closed schemas and the
service-supervisor inventory boundary are documented in
[`docs/ADAPTIVE_CAPACITY_AUDIT.md`](docs/ADAPTIVE_CAPACITY_AUDIT.md).

## Receipt-feed 1.1 operational bootstrap

Receipt-feed 1.1 is a one-way, review-only dashboard projection. Each canonical
receipt adds a caller-sanitized `publicLabel`, coarse `ownerClass` and
`laneClass`, a lifecycle-derived `nextSafeMove`, and explicit evidence age.
Labels are 1–80 characters from a narrow printable allowlist; paths, URLs,
emails, UUID-like identities, secret terms, and non-allowlisted classes fail
closed. Metadata may enter the live ledger only through optional
`prepare-launch.public_metadata` or `record-handback.public_metadata`.
Handback metadata supersedes launch metadata. Raw prompts, titles, target
paths, URLs, emails, thread/task IDs, and payloads are never projected.

When no authoritative orchestrator database exists, `reconcile-manifest`
imports one complete caller-supplied, allowlisted current-task manifest into a
canonical mode-`0700` local directory. The persisted state contains only typed
launch/handback receipts, sanitized public metadata, bounded typed evidence,
coarse keys, and explicit provenance. It neither calls an agent-CLI API nor stores a
raw task response. A monotonic manifest revision makes replay idempotent and
rejects stale or changed same-revision input. Canonical and mirror receipts are
retained for provenance, while mirrors and unresolved duplicate revisions are
excluded from dashboard counts.

From the repository root, the synthetic current-state acceptance path is:

```bash
FEED_STATE_DIR="$(mktemp -d)"
FEED_PUBLISH_DIR="$(mktemp -d)"

docker run --rm \
  -v "$PWD:/repo:ro" -v "$FEED_STATE_DIR:/state" \
  -w /repo python:3.12-slim \
  python -B addons/orchestrator_session/common/orchestrator-control/receipt_feed_exporter.py \
  reconcile-manifest \
  --request addons/orchestrator_session/common/orchestrator-control/receipt-feed/synthetic-current-task-manifest.json \
  --state-dir /state

docker run --rm \
  -v "$PWD:/repo:ro" -v "$FEED_STATE_DIR:/state" \
  -v "$FEED_PUBLISH_DIR:/published" \
  -w /repo python:3.12-slim \
  python -B addons/orchestrator_session/common/orchestrator-control/receipt_feed_exporter.py \
  publish-state --state-dir /state --output-dir /published \
  --served-at 2026-07-28T22:00:05Z --stale-threshold-seconds 60
```

The publish step takes a locked read of canonical local state and atomically
writes deterministic content-addressed `receipt-feed-1.1.<sha256>.json` bytes,
`receipt-feed-current.json`, and `receipt-feed-lkg.json`. On the next distinct
publish it also preserves `receipt-feed-previous.json`. A valid stale/degraded
projection may become current with that state explicit in its bytes while the
prior current remains the LKG; validation or privacy failure moves no pointer.
A Sites build may copy the snapshot plus pointer into its source archive as
static input. There is no hosted-to-Mac callback, polling, control endpoint, or
command channel.

Validate, migrate an old 1.0 snapshot, or swap current and LKG:

```bash
docker run --rm \
  -v "$PWD:/repo:ro" -v "$FEED_PUBLISH_DIR:/published" \
  -w /repo python:3.12-slim \
  python -B addons/orchestrator_session/common/orchestrator-control/receipt_feed_exporter.py \
  validate-snapshot --snapshot /published/receipt-feed-1.1.<sha256>.json

LEGACY_SNAPSHOT_DIR="/absolute/directory-containing-legacy-snapshot"
docker run --rm \
  -v "$PWD:/repo:ro" -v "$LEGACY_SNAPSHOT_DIR:/legacy:ro" \
  -v "$FEED_PUBLISH_DIR:/published" \
  -w /repo python:3.12-slim \
  python -B addons/orchestrator_session/common/orchestrator-control/receipt_feed_exporter.py \
  migrate-snapshot --snapshot /legacy/receipt-feed-1.0.json \
  --output-dir /published

docker run --rm \
  -v "$PWD:/repo:ro" -v "$FEED_PUBLISH_DIR:/published" \
  -w /repo python:3.12-slim \
  python -B addons/orchestrator_session/common/orchestrator-control/receipt_feed_exporter.py \
  rollback --output-dir /published
```

Migration creates explicit unavailable placeholders for the labels/classes that
1.0 never carried and derives only the coarse lane/action from lifecycle. It
does not infer a task title or owner identity.

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
delegated successor. Capacity configuration is a separate typed root-only
control: it requires the expected state revision and expected current capacity,
enforces bounds and the receipt-backed occupancy floor, and commits the new
capacity, one revision, one audit event, and one replay receipt atomically.

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
Until the active agent-CLI dispatcher calls it before every filesystem, process
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

Schema 1.3 adds an evidence-derived lifecycle watchdog. Call
`lifecycle-watchdog` after every worker message, wait timeout, and before a
status claim. Objective completion signals persist as
`COMPLETION_CANDIDATE` even if the worker still says `running`. Only fresh,
changed, explicitly typed remaining-work progress resets the bounded handback
counter. Two missed checks return `TERMINALIZE` and `INTERRUPT_REQUIRED`; the
slot remains owned until an exact interrupt receipt atomically releases the
claim, re-audits blocked work, reserves a successor or proves
`EMPTY`/`OWNER_GATED`, and creates the archive fence. `status` exposes
`reconciliation_required_task_ids` and does not authorize a plain running
claim for completion candidates.

## Stable commands

| Command | Contract |
|---------|----------|
| `record-policy-rule` | CAS a typed, scoped, privacy-safe learned rule into the live ledger with monotonic rule and policy revisions. |
| `configure-capacity` | Compare-and-set configured worker capacity from one expected bounded value and exact state revision; reject stale, unsafe, below-occupancy, or conflicting input and atomically record the revision, audit event, and truthful replay receipt. |
| `prepare-launch` | Resolve and explain effective rules; reject duplicate source/outcome/idempotency or overlapping ownership; atomically reserve the task, claim, fence, envelope, and `CREATE_THREAD` outbox before external creation. |
| `effective-rules` | Show included and excluded rules with deterministic reason codes and precedence evidence. |
| `record-launch-receipt` | Require the exact policy/rule/fence echo and external task ID before state becomes `RUNNING`. |
| `reconcile-external-task` | Confirm the receipt-backed external task or return immediate `STOP_READ_ONLY`, zero-change handback, archive, and capacity-exclusion instructions for a platform-created mirror. |
| `classify-decision` | Return `PM_PROXY` or `OWNER_GATE`; unknown/unsafe input is denied to the orchestrator and zero-step hosted-CI billing blockage is unexecuted infrastructure, never an owner prompt. |
| `takeover-lease` | Advance lease epoch and fencing only after the active lease expires. |
| `record-heartbeat` | Extend only the current fenced owner lease; stale workers are rejected. |
| `record-handback` | Validate exact refs, typed checks, CI/deployment/privacy truth, owned resource disposition, and normalized terminal observation; atomically release capacity, reserve an optional successor, and durably start the fenced closure/refill saga. |
| `capacity-watchdog` | Reconcile a durable saga after an event loss or crash, optionally reserve one exact successor, and expose a visible deficit until receipt-derived capacity is satisfied. |
| `lifecycle-watchdog` | Reconcile worker messages/timeouts/status claims against objective completion evidence; bound handback waits; require an exact interrupt receipt; and atomically refill before archive. |
| `record-archive-receipt` | Complete the archive outbox idempotently only after the successor launch receipt or evidenced `EMPTY`, `OWNER_GATED`, or `CAPACITY_FULL` outcome. |
| `reconcile-legacy-archive` | Compare-and-set one exact completed task through its pending archive outbox only after a released claim, canonical launch receipt, independent external archive proof, and bounded proof that the old transport ticket is missing. |
| `reconcile-stale-present-archive` | Compare-and-set one exact terminal task through its pending archive outbox only after a unique stale ticket, independent external archive proof, and an admissible authoritative EMPTY or archived-successor refill chain are rechecked atomically. |
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
`interrupted/notLoaded` closeout, completion-candidate terminalization,
fresh-progress preservation, interrupt/refill/archive fencing, crash rollback, stale fences,
rule conflict quarantine, CI truth, privacy, unsafe dashboard links, exact
bucket assignment, sparse/conflicting priors, waiting-time exclusion,
underestimate rollover, early finish, reclassification crash/race recovery,
fair scheduling/setup failure, capacity compare-and-set bounds/floor/replay,
crash rollback and concurrent preparation, and the root-role regressions for self-assigned
estimation/design, repository inspection, premature completion claims after
`send_message`, and receiptless capacity fill.
