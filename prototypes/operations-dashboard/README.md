# Unified operations dashboard sources

Firestarter preserves two complementary dashboard surfaces:

- `../operations-floater/` is the native macOS control surface. It may read
  locally verified state from its sandboxed Application Support container. It
  never transmits that state.
- `../operations-dashboard-web/` is the browser snapshot surface. It renders
  only an explicitly supplied, sanitized snapshot. It never fetches from or
  bridges to a Mac.
- `contract/` is the only shared data boundary. Both surfaces validate the same
  `queue`, `tests`, `resourceBudget`, and `signals` record arrays. Every record
  carries explicit `exposure` and `verification` metadata.

## Source ownership

Keep shared-contract changes under this directory, native-only changes under
`../operations-floater/`, and web-only changes under
`../operations-dashboard-web/`. Separate commits should not modify another
surface's files.

## Privacy boundary

Committed source and fixtures contain generic examples only. Do not commit:

- credentials, identity headers, account or signing identifiers;
- hostnames, domain names, IP addresses, ports, URLs, or tailnet/DNS names;
- local or home-directory paths;
- project, patient, customer, or machine names;
- live queue contents, timestamps, resource counts, or telemetry values.

Native runtime state may contain local-only records, but every local-only record
must be marked `verified`. Native foreground and pinning controls stay in the
native adapter and are not part of the shared snapshot. A web snapshot must use
`sanitized-remote` mode and contain only `sanitized` records.

Run the shared checks with:

```bash
node --test prototypes/operations-dashboard/tests/*.test.mjs
```

`bin/publish-sanitized.mjs` implements the offline, one-way publication adapter.
See [PUBLISHING.md](PUBLISHING.md) for immutable release creation, activation,
verification, rollback, and failure behavior.
