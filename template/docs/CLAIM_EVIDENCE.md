# Evidence-bound claims

Before a categorical absence, source-provenance, active-worker, or confirmed
appointment statement, validate a structured evidence envelope with
`scripts/claim-evidence.py`. Use the project's Docker Python runner, passing JSON
on stdin. Exit 0 permits the scoped statement; exit 1 requires qualification or
blocks it; exit 2 rejects malformed input. Never turn nonzero into a confident
claim. The output contains only stable decision codes, not source text.

## Contract

The envelope has exactly five fields: `kind` (`observation`, `absence`,
`provenance`, `worker_active`, `appointment`), `now` (UTC Unix seconds),
`max_age_seconds` (positive, at most one day), `required_scopes` (unique nonempty
source names), and `evidence` (a list). Choose a shorter freshness budget for
volatile worker/appointment state; a one-day maximum is not a recommendation.

Each evidence item has exactly these fields:

- `id`: unique source observation ID.
- `scope`: one of the independently chosen required scopes.
- `source_class`: `primary`, `reported`, `inferred`, or `synthetic`.
- `reference`: retrievable source reference, privately retained by the caller.
- `observed_at`: observation time in UTC Unix seconds, not ingestion time.
- `result`: `supports`, `contradicts`, `not_found`, or `unavailable`.
- `coverage_complete`: true only after pagination, query limits, read errors,
  paths outside the main checkout, and relevant connected sources are accounted for.
- `state`: null, `active`, `idle`, `scheduled`, `confirmed`, or `cancelled`.

A scope inventory must be selected before searching, using the question and
known source map. A partial checkout is not the entire project. An allowed
absence is only absence within the recorded scopes and time, never universal
absence. Report unsearched/unavailable scopes plainly. Do not shrink scope to
make a gate pass. Conflicts remain blocked until reconciled against fresh
primary evidence; do not discard inconvenient sources.

`primary` means inspected original content or authoritative current tool
receipt. A worker's prose report is `reported` until checked. A generated
practice question is `synthetic`, never an original exam item. A reasoned
conclusion is `inferred`, never a quotation. The guard checks classification
and completeness; it cannot infer whether a citation actually entails a claim.
For exact provenance, verify original content and source identity first. The
reviewed-extraction add-on additionally verifies byte digests and span bounds.

For active work, feed fresh receipt-derived lifecycle state from the existing
PM-proxy/watchdog. A sent instruction, scheduled check, or idle worker is not
active implementation. Keep `work-receipt.sh` for acceptance/completion receipts;
this guard does not replace or create a worker, scheduler, or controller.
For appointments, inventory both `calendar` and `messages`; a generic family
block is not a confirmation. Check matching identity, date, time zone, service,
and later cancellation/rescheduling before marking a source `confirmed`.

## Enforcement and limitations

This is a pure offline validator and reusable pre-send integration point.
Generated instructions and CI regression tests are shipped; no chat platform
send hook, live scheduler, security setting, or deployed runtime is changed.
A caller can bypass it or provide inaccurate classification, times, scope, or
state. Therefore passing it is not proof of truth, identity, completeness,
authenticity, or successful delivery. Mandatory enforcement needs an authorized
adapter on the actual send path and end-to-end tests there. Do not claim the
assistant can no longer make these errors.

Adoption: source adapter -> classify/verify -> build scope envelope -> validate
-> permit the scoped statement only on allow. On qualify, state what is known,
what was checked and what remains unknown; on block, reconcile or retract the
claim. The caller owns claim-to-source binding and freshness policy. Keep raw
private evidence out of Git, public reports, fixtures, and diagnostics.

Regression suite: `tests/test_claim_evidence_contract.py` uses synthetic cases
for partial-repository absence, invented provenance, idle and stale workers,
and generic calendar blocks with missing message confirmation. It also tests
conflicts, malformed input, duplicate keys, and no source-text output.
Rollback is removal of this opt-in validator and its instruction reference;
no external state or private data is mutated by evaluation.
