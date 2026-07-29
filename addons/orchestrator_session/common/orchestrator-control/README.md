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
- The caller selects a local state directory. The CLI enforces directory mode
  `0700`, database mode `0600`, current-user ownership, and no symlink path
  components.
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

## Stable commands

| Command | Contract |
|---------|----------|
| `record-policy-rule` | CAS a typed, scoped, privacy-safe learned rule into the live ledger with monotonic rule and policy revisions. |
| `prepare-launch` | Resolve and explain effective rules; reject duplicate source/outcome/idempotency or overlapping ownership; atomically reserve the task, claim, fence, envelope, and `CREATE_THREAD` outbox before external creation. |
| `effective-rules` | Show included and excluded rules with deterministic reason codes and precedence evidence. |
| `record-launch-receipt` | Require the exact policy/rule/fence echo and external task ID before state becomes `RUNNING`. |
| `classify-decision` | Return `PM_PROXY` or `OWNER_GATE`; unknown/unsafe input is denied to the orchestrator and zero-step hosted-CI billing blockage is unexecuted infrastructure, never an owner prompt. |
| `takeover-lease` | Advance lease epoch and fencing only after the active lease expires. |
| `record-heartbeat` | Extend only the current fenced owner lease; stale workers are rejected. |
| `record-handback` | Validate exact refs, typed checks, CI/deployment/privacy truth, and owned resource disposition; atomically start predecessor archive and optional successor saga. |
| `record-archive-receipt` | Complete the archive outbox idempotently after the external archive succeeds. |
| `recycle-queue` | Audit every blocked item in one transaction and rank the highest-value safely resumable work before lower-value replenishment. |
| `migrate-decisions` | Dry-run or quarantine legacy `{generated,items}` board bytes; map `decide` to needs-classification and `play` to showcase/non-work without producing owner notifications or task authority. |
| `status` | Export a privacy-bounded local view of rules, tasks, decisions, reasons, and outbox state. |

## Exit semantics

| Exit | Meaning |
|------|---------|
| `0` | Operation committed or valid read/classification returned. |
| `2` | Invalid schema/privacy/receipt/fence or denied unsafe action; do not mutate or create externally. |
| `3` | Duplicate, owner, priority, idempotency, lease, or policy conflict; stop read-only and reconcile. |
| `4` | State unavailable/corrupt or unexpected failure; fail closed. |

Success is one JSON object on stdout. Failure is one JSON object on stderr.
Tests cover process races, crash rollback/recovery, fences, rule precedence and
conflict quarantine, CI truth, migration preservation, privacy, and unsafe
dashboard links.
