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

When unavailable, `value` must remain `null`; it never becomes `0`, `false`,
`[]`, `idle`, `stopped`, or `healthy`.

Each service is exactly:

- `id`
- `displayName`
- `manager { kind, identifier, state }`
- `listener { declared, observed }`
- `health { probe, status }`
- `ownership { owner, retainPolicy, managed:false }`
- `dependencies`
- `resourceClass`

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
exists. Generic container names are not ownership evidence. Ollama resident
models remain observe-only facts and never authorize load, unload, or pull.

## Current source-only findings

The producer currently classifies Caddy, the Ollama host, and Relay as
never-stop. Router, Recall, and Triage have desired loopback declarations, but
source hardening is not proof of a live binding change. All other lifecycle
policy remains manual or scheduled.

No Caddy reload, listener change, launchd action, Docker action, Ollama action,
or other host mutation follows from this document.
