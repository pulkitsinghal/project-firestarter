# Adaptive capacity audit

`adaptive_capacity_policy.py` is a deterministic companion evaluator for one
closed host-metrics snapshot. It is deliberately outside the authoritative
SQLite launch transaction:

- it does not collect host metrics;
- it does not write state, reserve a worker, or change a scheduler generation;
- it does not admit, pause, stop, wake, or restart work;
- it does not consume service-supervisor inventory; and
- every response says `mode: audit`, `enforcement_applied: false`,
  `reservation_created: false`, `source_authority_verified: false`, and
  `service_actions_authorized: false`.

This boundary lets operators compare an advisory cap with the current
receipt-backed scheduler without turning caller-supplied metrics into authority.
`memory_pressure_pct` remains an unpinned normalized input. Both permitted
source kinds are therefore non-authorizing.

The exact reviewed adaptive-capacity integration packet receipt is pinned at
SHA-256
`9655dcc04d53b5e48dbf50c1c963af9d79cc935a4071fd129ccb01e9b274c9e6`.

## Run one synthetic audit

```bash
python -B orchestrator-control/adaptive_capacity_policy.py \
  --request /path/to/adaptive-capacity-request.json
```

The request and response are closed by:

- `schemas/adaptive-capacity-audit.request.schema.json`
- `schemas/adaptive-capacity-audit.response.schema.json`

The snapshot digest binds `snapshot_id`, the coarse source descriptor, and the
exact metrics including `observed_at`. `request_id`, `now`, and
`visible_limit` are evaluation context, so they do not change snapshot identity.
Age is computed from `observed_at` and `now`; callers cannot submit an
`age_seconds` override. A snapshot older than 60 seconds contracts
conservatively.

## Service-supervisor boundary

The reviewed supervisor dry-run packet was pinned to Firestarter
`518db9d0c4df310c85e0175895a56cf97429f6d6` and validation receipt fields:

- validation receipt SHA-256
  `3a4af3e78f68a81502b907a9d0c41be92e07092e7f3f0895319dd14f6e1948f5`

- `status: passed`
- 40 synthetic tests passed
- `dry_run: true`
- `permit_authority: false`
- `execution_authority: false`
- `executable: false`
- `live_service_actions: false`
- `network_listener: false`

Its historical reduced inventory is not a capacity snapshot. It included stale
Docker identity and endpoint metadata, lacked readable launchd inventory, and
contained wildcard-published endpoint observations that must fail a future
loopback-only gate. No name discovered by inventory creates an allowlist entry.
No adaptive result can authorize a service action.

The following remain separate prerequisites before any enforcement work:

1. a content-addressed immutable snapshot store;
2. pinned collector semantics and units;
3. non-spoofable worker-owner and parent-bound sublane receipts;
4. authoritative runtime active/waiting state and legacy reconciliation;
5. SQLite generation, idempotency, crash, and race coverage;
6. a separately reviewed typed real-service adapter and one-use permit; and
7. real dispatcher-denial evidence before a universal root claim.

Until then, `prepare-launch`, refill, and service-supervisor behavior are
unchanged. Rollback is a normal source revert; there is no migrated state.
