# Observe-only local-ai inventory mapping

## Authority boundary

The local-ai producer contract is observe-only. Its root identifies
`schemaVersion: "1.0"` and `mode: "observe-only"`, and every catalog ownership
record carries `managed: false`. Those facts are inventory evidence only. They
never authorize the Firestarter supervisor to start, stop, retain, probe, bind,
or otherwise manage a service.

Version 0.1.0 of `service_supervisor` does not ingest the producer at runtime.
Its only executable adapter remains `synthetic`. This mapping records the
future integration seam without weakening either contract.

Canonical producer artifacts are:

- `service_catalog.json`
- `service_inventory.py`
- `docs/service-inventory-1.0.schema.json`
- `docs/SERVICE_INVENTORY.md`

Representative downstream fixtures are:

- `tests/fixtures/service-catalog-1.0.synthetic.json`
- `tests/fixtures/service-metrics-1.0.synthetic.json`
- `tests/fixtures/service-inventory-1.0.synthetic.json`

## Producer shape

The inventory root is exactly:

- `schemaVersion`
- `mode`
- `generatedAt`
- `services`
- `dockerCompose`
- `ollama`
- `privacy`

Every observed runtime fact is exactly:

```json
{
  "value": null,
  "available": false,
  "source": "declared-or-observed-source",
  "observedAt": null,
  "reason": "bounded-reason-code"
}
```

When `available` is `false`, `value` must remain `null` and `reason` must be
non-null; unknown never becomes `0`, `false`, `[]`, `idle`, `stopped`, or
`healthy`. When `available` is `true`, `value` must be non-null and `reason`
must be `null`. The schema constrains contextual values instead of accepting
arbitrary status strings.

Each service is exactly:

- `id`
- `displayName`
- `manager { kind, identifier, state }`
- `listener { declared, observed }`
- `health { probe, status }`
- `ownership { owner, retainPolicy, managed:false }`
- `dependencies`
- `resourceClass`

`manager.state` is one of `loaded`, `not-loaded`, or `reachable`.
`listener.observed.value`, when available, is exactly
`{addresses: [], exposure: ...}`. `health.status` is either `healthy` or
`unavailable`; it is not a supervisor lifecycle state.

`ollama.models.value`, when available, is a list of exact
`{name, resident:true, sizeGb}` records. `sizeGb` is itself an
availability-wrapped observation, so an unknown model size remains
`value:null, available:false` rather than becoming zero.

## Fail-closed mapping

| local-ai field | supervisor catalog field | Rule |
|---|---|---|
| `id` | `id` | Must pass the supervisor service-ID regex and remain unique. |
| `manager.kind` | `adapter` | Use a reviewed, hard-coded mapping only. Unknown kinds refuse. v0.1 has no mapping because only `synthetic` is accepted. |
| `listener.declared` | `upstream` | Requires an available loopback IP literal, valid port, HTTP transport, and unique target. Wildcard, LAN, DNS-name, missing, or unavailable declarations refuse. |
| `dependencies[]` | `dependencies[]` | All IDs must exist; duplicates, self-dependencies, and cycles refuse. |
| `health.probe.path` | `health.path` | Fixed GET path only; query, fragment, credentials, missing, or unavailable probes refuse. |
| `ownership.retainPolicy` | `never_stop`, `retain` | Exact `never-stop` may map to both `true`; all other policies require explicit Firestarter policy. |
| inventory timing | lifecycle timeouts | Never mapped. Wake, idle, and drain timeouts remain reviewed Firestarter policy. |
| observed facts | runtime state/metrics | Availability is preserved. Unknown facts stay `null + available:false` and never become a lifecycle state or numeric zero. |
| `ownership.managed` | execution authority | Must be exactly `false` for this producer and is never promoted to permission. |

Docker Compose stays unavailable unless an exact approved project declaration
exists. Declared and current Compose status are separate observations; generic
container names are not ownership evidence. Ollama resident models remain
observe-only facts and never authorize load, unload, or pull.

## Current source-only findings

The producer currently classifies Caddy, the Ollama host, and Relay as
never-stop. Router, Recall, and Triage have desired loopback declarations, but
source hardening is not proof of a live binding change. All other lifecycle
policy remains manual or scheduled.

The reviewed dependency observations are:

- `router -> [ollama-host]`
- `recall`, `triage`, and `browse -> []`
- `stream-ingest -> [ollama-host]`
- `pm-loop -> [relay]`

Browse declares a fixed `GET /health` probe. These edges and the probe remain
inventory inputs only; observed manager/listener/health facts must never be
promoted into a Firestarter supervisor lifecycle state.

No Caddy reload, listener change, launchd action, Docker action, Ollama action,
or other host mutation follows from this document.
