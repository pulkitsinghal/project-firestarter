# Service supervisor

This opt-in Firestarter tool is a source-safe service catalog, deterministic
planner, and synthetic lifecycle reference. Version 0.1.0 cannot control a real
service: the only accepted adapter is `synthetic`, and the shipped module has
no listener, subprocess, Docker API, Docker socket, launchd integration, Ollama
integration, or deployable proxy.

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

Neither command starts the synthetic adapter or opens a listener.

## Contract

- Exact catalog keys; unknown adapters/fields/services refuse.
- IP-literal loopback targets only.
- Acyclic dependency graph with deterministic topological wake and reverse
  idle planning.
- `STOPPED`, `STARTING`, `READY`, `DRAINING`, and `FAILED` states.
- Concurrent wake singleflight, bounded readiness, dependency leases,
  cancellable drain grace, `never_stop`, retain pins, rollback, and shutdown
  cleanup.
- Bounded transition telemetry with no URLs, paths, queries, headers, bodies,
  commands, secrets, or private content.
- Unknown CPU/memory values stay `null` with `available:false`.

The test module contains a loopback-only GET/HEAD fixture to prove that a future
data plane waits for readiness and never forwards refused body methods. It is
test code, not an installation candidate.

Read [the operator runbook](docs/OPERATOR_RUNBOOK.md) for the Caddy/local-ai
boundary, test command, execution gate, and rollback conditions.
The [observe-only inventory mapping](docs/LOCAL_AI_INVENTORY_MAPPING.md)
records the exact unknown-preserving producer seam without granting management.
