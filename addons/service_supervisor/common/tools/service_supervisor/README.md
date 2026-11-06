# Service supervisor

This opt-in Firestarter tool is a source-safe service catalog, deterministic
planner, synthetic lifecycle reference, and typed PM execution-permit verifier.
Version 0.2.0 cannot control a real service: the lifecycle runtime's only
adapter is still `synthetic`, and the permit verifier can only return a
separately signed `AUTHORIZED_FOR_EXECUTOR_HANDOFF` receipt for a future
broker/executor boundary. The shipped
module has no listener, subprocess, shell, Docker API, Docker socket, launchd
integration, Ollama integration, network client, or deployable proxy.

## Read-only commands

Validate the strict example catalog:

```bash
python -m tools.service_supervisor validate \
  --manifest tools/service_supervisor/services.example.json
```

Print a deterministic dependency-ordered wake plan:

```bash
python -m tools.service_supervisor plan-wake \
  --manifest tools/service_supervisor/services.example.json \
  --service synthetic-api
```

Print a non-executing recovery-ladder plan (probe → revive → confirmed failover
→ retest) for a service that declares a `recovery` policy:

```bash
python -m tools.service_supervisor plan-recovery \
  --manifest tools/service_supervisor/services.example.json \
  --service synthetic-api \
  --observation tools/service_supervisor/recovery-observation.example.json
```

None of these commands start the synthetic adapter or open a listener.

The permit verifier is an import-only control-plane API. It validates the
strict local-ai plan/result seam, checks an HMAC-SHA256 PM permit against an
in-memory trusted keyring, and atomically consumes the permit nonce in a
mode-`0600` SQLite ledger. It signs the returned, short-lived handoff receipt
with a distinct in-memory key and exact verifier/pin provenance. Keys are
injected by the future integrating process; there is no signing CLI, key file
format, environment-variable convention, broker, or executor in this package.

## Contract

- Exact catalog keys; unknown adapters/fields/services refuse.
- IP-literal loopback targets only.
- Acyclic dependency graph with deterministic topological wake and reverse
  idle planning.
- Optional, default-inert recovery ladder. A declared `recovery.liveness` probe
  is distinct from `health` (registration is not readiness); `revive` and
  `failover` actions stay off unless enabled; `plan_recovery` only plans, never
  executes. Enumerated-but-unreachable never reads healthy, failover to an
  unconfirmed alternative is refused, revive is bounded and does not loop, and
  demotion is reversed on a confirmed retest.
- `STOPPED`, `STARTING`, `READY`, `DRAINING`, and `FAILED` states.
- Concurrent wake singleflight, bounded readiness, dependency leases,
  cancellable drain grace, `never_stop`, retain pins, rollback, and shutdown
  cleanup.
- Bounded transition telemetry with no URLs, paths, queries, headers, bodies,
  commands, secrets, or private content.
- Unknown CPU/memory values stay `null` with `available:false`.
- Local-ai plan bytes use sorted compact ASCII JSON; `plan_digest` is SHA-256
  over the exact root with that field omitted.
- Plans contain only discriminated adapter operations, exact argv arrays or a
  fixed loopback Ollama request, typed readiness, and typed inverse rollback.
- PM permits are signed and bound to exact scope and generations. Apply and
  rollback require different permit phases and nonces.
- Serialized handoff authority is a separately signed, one-use receipt. The
  future broker must pin its provenance and atomically consume its independent
  nonce; the PM permit key cannot sign it.
- Nonces and revocations survive restart and are consumed atomically once.
- Authorization is not execution and inventory observations remain non-authority.

The test module contains a loopback-only GET/HEAD fixture to prove that a future
data plane waits for readiness and never forwards refused body methods. It is
test code, not an installation candidate.

The [recovery ladder](docs/RECOVERY_LADDER.md) defines the
probe/revive/confirmed-failover/retest policy, the fail direction at each rung,
and the dry-run-first requirement. It is OS-neutral: the policy and evidence
requirements are the lift, never a platform command.

Read [the operator runbook](docs/OPERATOR_RUNBOOK.md) for the Caddy/local-ai
boundary, test command, execution gate, and rollback conditions.
The [observe-only inventory mapping](docs/LOCAL_AI_INVENTORY_MAPPING.md)
records the exact unknown-preserving producer seam without granting management.
The [permit verifier contract](docs/PERMIT_VERIFIER.md) and
[migration/rollback guide](docs/PERMIT_MIGRATION_ROLLBACK.md) define the 0.2
boundary and its fail-closed producer pin.
