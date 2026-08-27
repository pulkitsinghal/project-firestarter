# Rollback decision frame

<!-- rollback-decision-frame:start -->
Rollback is a recovery decision, not execution authority. This guide chooses a
safe lane after a bad release; it does not grant production access, credentials,
or permission to mutate live state. Follow the preview-first irreversible-action
contract in [`AGENTS.md`](../AGENTS.md). Production database restores remain
owner-gated even when an application deploy is self-authorized.

## Stop and classify before changing anything

Classify dependencies, then pause only affected deploys, migrations, writers,
and repair attempts that could widen the incident. Keep monitoring, containment,
safety, and reconciliation workers running unless evidence shows they cause
harm. Preserve privacy-safe evidence of the current release, candidate
last-known-good release, database migration head, recovery point, and observed
failure. Public or repository records use opaque identifiers; provider IDs,
customer data, credentials, and production details stay in an approved private
store.

A release has two primary recovery lanes, but they are not the whole incident:

| Lane | Typical fault | Preferred recovery | Data consequence | Required evidence |
|---|---|---|---|---|
| **Application / release** | Bad code, static assets, or runtime configuration | Promote the exact last-known-good immutable artifact | Promotion does not itself recover state; resumed old code can still read or write it incorrectly | Artifact provenance, current-schema read/write compatibility, config compatibility, and live verification |
| **Database / state** | Destructive or semantically wrong migration, or corrupted app-owned data | Prefer a forward repair; restore a tested recovery point only when repair cannot meet the recovery objective | A restore may discard every write after the selected point | Recovery-point scope/freshness, restore drill, accepted RPO/RTO, owner authorization, and reconciliation plan |

Treat disclosure and downstream effects separately. Neither lane retracts a
disclosure, unsends a message or webhook, reverses a payment, revokes a copied
credential, or repairs another system automatically. Inventory and compensate
those effects explicitly; infrastructure rollback is not erasure.

## Choose the smallest safe lane

### 1. Application-only rollback — primary when compatibility is proved

Promote the prior artifact without touching the database only when all of these
are true:

- the exact target artifact is immutable, provenance-verified, and previously
  known good;
- that target's reads and writes are proven against the current schema and data
  semantics, including permissions, jobs, and queued messages;
- required configuration, feature flags, credentials, and external contracts
  still match; and
- the audience and content classification are already authorized under
  [`DEPLOY_POLICY.md`](DEPLOY_POLICY.md).

Use the repository-owned promotion/rollback command when one exists. If the
project has no reviewed command, create an `owner-action` runbook instead of
inventing provider commands during the incident. Immediately verify the exact
artifact and critical path with `make verify-live BASE=https://… EXPECT=<build-id>`
plus reviewed, bounded, production-safe probes that use synthetic identities.
Do not run a generic API/E2E suite against production. Any probe that mutates
state, sends a message, spends money, or discloses content must pass the
preview-first irreversible-action gate.

If promotion or verification fails, stop. Re-promote the current known artifact
when that is the safe compensation, or ship a forward fix. Do not cycle between
artifacts while compatibility or the live outcome is indeterminate.

### 2. Mixed release + migration — compatibility decides

An expand/transition/contract migration can preserve a deliberate rollback
window:

1. **Expand:** add backward-compatible structures without removing the old
   contract.
2. **Transition:** deploy a compatibility seam, backfill when needed, and prove
   the current application with the current schema and the
   previous application with the current schema. When mixed-version rollout or
   recovery requires it, also prove the current application with the previous
   schema. Exercise representative data semantics in every required pairing.
   Dual-write is optional; when used, prove idempotency and convergence before
   relying on it.
3. **Contract:** remove the old contract only after the rollback window closes
   and no supported release depends on it.

Compatibility is executable evidence, not an adjective. "Additive" SQL can
still break an older release through changed constraints, defaults, permissions,
triggers, enums, data meaning, or external contracts. If N-1 compatibility is
missing, stale, or failed, do not roll application code back blindly. Prefer a
forward fix or a coordinated application-and-schema recovery plan.

### 3. Database/state recovery — rare, destructive, owner-gated

Prefer the forward-only repair described in
[`migration-rollback.md`](migration-rollback.md). Restore only when the bad
migration or corruption cannot be repaired within the accepted recovery
objective and the restore gate below is complete.

Before every production migration, prove a usable recovery point exists. Bind
it to the source environment, consistency boundary, migration head,
artifact/config revision, format/engine version, checksum, key availability,
retention through the rollback window, expected recovery-point objective (RPO),
expected recovery-time objective (RTO), and exact path used by the last
successful isolated restore drill. A backup file or provider badge is not
restore proof. Inventory app-owned and provider-managed dependencies needed for
application integrity; restore only the explicitly reviewed scope unless a
broader provider runbook has been tested.

Before a restore:

1. quantify which writes and downstream effects occurred after the recovery
   point, state the estimated write-loss window, and obtain explicit owner
   acceptance of that loss/compensation plan;
2. restore into an isolated target first and run schema, data-integrity,
   application, and reconciliation checks;
3. capture a fresh pre-restore recovery point when doing so is safe and cannot
   overwrite, expire, or contaminate the known-good evidence;
4. preview the exact source point, destination, scope, cutover, write-fence,
   rollback-of-the-restore path, RPO/RTO, and affected consumers;
5. drain or park affected queues and jobs, record a final high-water mark, then
   verify affected writers reject new writes and fence stale writers until
   recovery verification completes; and
6. obtain fresh one-use scope-bound owner authorization and persist the
   sanitized write-ahead intent before the provider call.

Reuse the same idempotency key through reconciliation. If the provider outcome
or journal append is uncertain, report `indeterminate`, preserve evidence, and
reconcile before any retry. Never substitute a generic `dump --clean` or
provider-console recipe for the project's tested restore runbook.

## Close the incident truthfully

After either lane:

1. prove the live artifact/configuration and database migration head;
2. exercise the failed user/API path plus bounded production-safe read/write,
   health, authorization, queue/job, and data-integrity checks;
3. reconcile messages, webhooks, payments, caches, search indexes, analytics,
   and other external effects without assuming they followed the rollback;
4. record actual data loss, disclosure, unavailable evidence, and residual risk;
   and
5. write the postmortem and add a guardrail that prevents recurrence.

Do not infer statelessness from a DB-less stack. First inventory browser-local
or synchronized state, queues, object storage, caches, files, and third-party
state; only then may the database lane be marked N/A. Application rollback and
external-effect reconciliation still apply. For a worker or API, "application"
means its immutable release artifact. For an extension or other asynchronously
updated client, account for store review, gradual rollout, and mixed installed
versions; a new corrective version may be safer than trying to promote an old
artifact.

## Related runbooks

- [`DEPLOY_POLICY.md`](DEPLOY_POLICY.md) — when an application deploy is
  self-authorized and which substeps remain owner-only.
- [`GO_LIVE.md`](GO_LIVE.md) — release and live-verification checklist.
- [`migration-rollback.md`](migration-rollback.md) — forward corrective
  migrations and emergency database procedure.
- [`UNLISTED_PUBLISHING.md`](UNLISTED_PUBLISHING.md) — why rollback cannot
  retract a disclosure.
<!-- rollback-decision-frame:end -->
