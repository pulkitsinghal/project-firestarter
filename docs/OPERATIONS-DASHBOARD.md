# Unified operations dashboards

Firestarter includes an opt-in reference implementation for showing the same
operational model in two places without turning a browser into a workstation
back door:

| Surface | Intended data | Network behavior |
|---|---|---|
| Native macOS floater | Canonical local snapshots, including verified `local-only` records | Reads its sandboxed local store; does not transmit it |
| Static web dashboard | An explicitly produced `sanitized-remote` snapshot | Loads one static snapshot into a responsive ten-lane reference view; does not poll or connect to a workstation |

These prototypes are reusable source under `prototypes/`; the Firestarter
generator does not stamp them into new projects by default.

## Shared contract

Both surfaces validate contract version `1.0`. The root contains:

- `mode`: `local` or `sanitized-remote`;
- `queue`: current and queued operational work;
- `tests`: validation results and unimplemented gaps;
- `resourceBudget`: measured or estimated scheduling capacity; and
- `signals`: availability and attention indicators.

Every record includes:

- `exposure`: `sanitized` or `local-only`; and
- `verification`: `verified`, `estimated`, `unavailable`, or
  `not-implemented`.

An unrun test is not a passing test. Unavailable telemetry stays unavailable,
and scheduling estimates stay estimates. The native adapter additionally
requires every `local-only` record to be verified. A remote snapshot must use
`sanitized-remote` mode and contain only sanitized records.

The shared contract intentionally has no endpoint, URL, host, IP, filesystem
path, credential, or identity fields. Native window controls, local provenance,
and source-file handling remain behind the native adapter.

## Try the static browser surface

Run the privacy tests in a throwaway container:

```bash
docker run --rm -v "$PWD:/repo:ro" -w /repo python:3.12-slim \
  python -m unittest discover prototypes/operations-dashboard-web/tests -v
```

Run the executable web validator unit tests:

```bash
docker run --rm -v "$PWD:/repo:ro" -w /repo node:22-slim \
  node --test prototypes/operations-dashboard-web/tests/*.test.mjs
```

Then serve the synthetic fixture locally:

```bash
docker run --rm -p 8080:8080 -v "$PWD:/repo:ro" -w /repo python:3.12-slim \
  python -m http.server 8080 -d prototypes/operations-dashboard-web
```

The browser renderer validates once and fails closed. It has no WebSocket,
polling loop, local agent, or Mac bridge. The committed fixture has exactly ten
synthetic lifecycle lanes and makes missing resource measurements, unrun tests,
and unimplemented automation visible instead of manufacturing positive
results. Desktop and narrow-screen evidence plus the compact failure/rollback
map live in
[`prototypes/operations-dashboard-web/docs/state-flow.md`](../prototypes/operations-dashboard-web/docs/state-flow.md).

## Use the native surface

Open `prototypes/operations-floater/OperationsFloater.xcodeproj` on macOS. The
app opens a compact floating dashboard and offers two explicit local actions:

1. **Import Local Snapshot…** validates a canonical `local` version `1.0`
   snapshot before installing it with private file permissions. Imports must be
   regular files no larger than one megabyte; symbolic links fail closed.
2. **Restore Previous Snapshot** validates and swaps back to the last retained
   valid snapshot.

The selected source path is not retained, invalid input cannot replace the
current snapshot, and missing or invalid runtime state falls back to the
committed generic sample. The app has no network updater.

See
[`prototypes/operations-floater/INSTALL_UPDATE_ROLLBACK.md`](../prototypes/operations-floater/INSTALL_UPDATE_ROLLBACK.md)
for signed-install preflight, update acceptance, and application rollback.

## Publish a sanitized static release

Publication is an explicit one-way, offline transform. It validates the full
local snapshot, drops all `local-only` records, copies only allowlisted fields,
rejects private-looking sanitized content, and builds a content-addressed
static release. Source snapshots must be regular files no larger than one
megabyte.

Choose operator-controlled source and publication directories outside Git:

```bash
SOURCE_DIR=...
PUBLICATION_DIR=...
```

Build, verify, and activate an immutable release:

```bash
docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$SOURCE_DIR:/input:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  build --input /input/dashboard-state.json --output-root /publication

RELEASE_ID=...
docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  verify --output-root /publication --release-id "$RELEASE_ID"

docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  activate --output-root /publication --release-id "$RELEASE_ID"
```

The deployable directory is `$PUBLICATION_DIR/current/`. Uploading it is a
separate authorized action because the destination, access policy,
credentials, retention, and remote rollback mechanism are environment-specific.
None belongs in reusable source.

Verify the publisher—including sanitization, tamper detection, HTTP retrieval,
activation, update, and rollback—with:

```bash
docker run --rm -v "$PWD:/repo:ro" -w /repo node:22-slim \
  node --test prototypes/operations-dashboard/tests/*.test.mjs
```

## Rollback and failure behavior

Before any deployment, retain the last known-good remote artifact or deployment
identifier. Locally, the publisher keeps immutable releases and a relative
`current` link. Roll back the local publication with:

```bash
docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  rollback --output-root /publication
```

The workflow stops on invalid records, unknown fields, unverified local-only
records, private-looking sanitized strings, symbolic-link or oversized inputs,
unexpected release files, symbolic links inside a release, or hash mismatches.
History is prepared before the active release changes; if its commit fails, the
publisher compensates by restoring the prior active release. It never logs the
source snapshot or retained record values and never deletes releases
automatically.

## Privacy review checklist

Before sharing any artifact:

- confirm `mode` is `sanitized-remote`;
- confirm every retained record is `exposure: "sanitized"`;
- keep unavailable telemetry and unimplemented tests explicit;
- run the shared and web privacy tests;
- inspect the artifact for identity, endpoint, URL, host, IP, path, credential,
  project, patient, customer, machine, and live-telemetry data;
- verify the immutable release hash before activation; and
- verify the destination access policy separately after deployment.
