# Local service supervisor operator runbook

## Proof boundary

Version 0.1.0 is a source-safe supervisor contract, not a Mac service manager. Its
only adapter is `synthetic`, which changes in-memory test state and never runs a
command. The shipped module exposes catalog validation, deterministic planning,
and lifecycle APIs only. It has no listener or proxy entrypoint. A small
loopback GET/HEAD data plane exists only inside the hermetic test module to
prove wake-before-forwarding.

A future installed design keeps Caddy responsible for TLS, authentication,
streaming, WebSockets, headers, queries, and private content, and places the
local-ai lifecycle wake broker on a mode-`0600` Unix socket that receives fixed
metadata only.

This release does **not** install anything, open the Docker socket, inspect
containers or private data, control launchd/Ollama, pause a process, or stop a
real service.

Do not replace `synthetic` with a command, launchd, Docker, or Ollama adapter
without a separately reviewed implementation and an explicit PM-proxy
execution gate proving every exact target disposable. Keep any user-visible,
required, shared-router, production, and externally bound service out of scope.

## Safety model

- Every catalog target must use an IP-literal loopback address.
- The manifest is the complete allowlist. Unknown keys, adapters, services,
  dependencies, cycles, unsafe URLs, and malformed health paths refuse startup.
`service-catalog.schema.json` documents the same exact key surface; runtime
validation remains authoritative for graph and loopback-IP semantics.
- The local-ai inventory stays a separate observe-only producer. Follow
  `LOCAL_AI_INVENTORY_MAPPING.md`: `managed:false` is never executor authority,
  unknown facts remain unavailable, and manager kinds require a reviewed fixed
  adapter mapping.
- The shipped supervisor opens no TCP or Unix listener and proxies no traffic.
- The test-only data plane permits GET and HEAD, refuses body methods before
  wake, and strips authorization, cookie, and request-framing headers.
- The first request waits for dependency health and target health within one
  bounded deadline. Concurrent first requests share a single wake attempt.
- A lease covers the target and its dependency closure. Idle stop begins only
  after the last lease, the idle interval, and a cancellable drain grace.
- `never_stop` and `retain` suppress idle stop. Supervisor shutdown still
  cleans up synthetic adapter-owned state.
- Telemetry contains service IDs and state/reason codes only. It never records
  paths, queries, headers, bodies, upstream responses, commands, or secrets.
- CPU and memory remain `null` with `available:false` until a truthful adapter
  exists; unknown is never reported as zero.
- The synthetic HTTP test fixture is not an installation candidate. Production
  integration must use the Caddy + metadata-only Unix-socket sentinel split
  before any real adapter or private route is considered.

## Validate the example without serving

Run inside the generated project's normal Docker tooling policy:

```bash
docker run --rm -v "$PWD:/work:ro" -w /work python:3.12-slim \
  python -m tools.service_supervisor validate \
  --manifest tools/service_supervisor/services.example.json
```

Expected output names only the synthetic adapter and allowlisted service IDs.
Validation must not open a listener or start an upstream.

## Inspect a deterministic wake plan

Planning is read-only. It does not start the synthetic adapter or open a
listener:

```bash
docker run --rm -v "$PWD:/work:ro" -w /work python:3.12-slim \
  python -m tools.service_supervisor plan-wake \
  --manifest tools/service_supervisor/services.example.json \
  --service synthetic-api
```

The JSON steps list `synthetic-cache` before `synthetic-api`. Repeating the
command produces the same plan. The example upstreams are not contacted and
are not claimed to exist.

## Test

```bash
docker run --rm -v "$PWD:/work:ro" -w /work python:3.12-slim \
  python -B -m unittest -v \
  tools.service_supervisor.tests.test_service_supervisor
```

## Rollback

Before any future installation, rollback is source-only: remove the add-on from
the generated project or regenerate with `include_service_supervisor=no`.
Version 0.1.0 creates no daemon, listener, launch item, container, volume,
secret, socket, state file, or host configuration to remove.

If a future real adapter is proposed, its change must add exact per-adapter
preflight, health proof, stop eligibility, rollback, locking, and crash-recovery
evidence before it is eligible for an execution gate.
