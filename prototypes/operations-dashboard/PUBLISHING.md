# Sanitized snapshot publication

This workflow creates an immutable static web release from an explicitly
supplied canonical local snapshot. It performs no upload, polling, discovery,
or workstation connection.

## Boundary

The publisher:

1. requires a version `1.0` snapshot in `local` mode;
2. validates the complete local snapshot before filtering;
3. drops every `local-only` record;
4. copies only the allowlisted fields for each shared record type;
5. changes the output mode to `sanitized-remote`;
6. rejects private-looking content in records marked `sanitized`;
7. rejects symbolic-link inputs and inputs larger than one megabyte;
8. creates a content-addressed, immutable web release; and
9. verifies every asset and snapshot hash before activation.

It does not attempt heuristic redaction. A record is either explicitly safe and
passes the privacy checks, or publication stops. This avoids turning an
incomplete redaction into a false privacy claim.

The browser never reads the native app's sandbox or a workstation endpoint. An
operator must deliberately provide the source snapshot to the offline publisher
and separately deploy the resulting static `current` directory.

## Build and verify

Set these shell variables to operator-controlled directories outside Git:

```bash
SOURCE_DIR=...
PUBLICATION_DIR=...
```

Run the dependency-free publisher in Docker:

```bash
docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$SOURCE_DIR:/input:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  build \
  --input /input/dashboard-state.json \
  --output-root /publication
```

The command prints a SHA-256 `releaseId`. Verify it before activation:

```bash
RELEASE_ID=...
docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  verify \
  --output-root /publication \
  --release-id "$RELEASE_ID"
```

## Activate and inspect

Activation atomically updates a relative `current` symbolic link. Existing
release directories are retained, and the previously active release is added to
the local rollback history. If the history update fails after the link changes,
the publisher restores the previously active release before reporting failure.

```bash
docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  activate \
  --output-root /publication \
  --release-id "$RELEASE_ID"
```

Inspect the active state without reading snapshot contents into logs:

```bash
docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  status \
  --output-root /publication
```

The deployable artifact is `$PUBLICATION_DIR/current/`. Uploading it to a
specific static host is intentionally outside this repository because that step
requires an authorized account, destination, retention policy, and rollback
mechanism. No deployment target or credential belongs in source control.

## Rollback

Rollback verifies the previous immutable release before switching `current`.
It retains the replaced release, so a subsequent rollback can reverse the
switch.

```bash
docker run --rm \
  -v "$PWD:/repo:ro" \
  -v "$PUBLICATION_DIR:/publication" \
  -w /repo node:22-slim \
  node prototypes/operations-dashboard/bin/publish-sanitized.mjs \
  rollback \
  --output-root /publication
```

After rollback, rerun `status`, serve the `current` directory through the
approved preview environment, and repeat the privacy and browser checks before
any external upload.

## Failure and cleanup

- Invalid local records, unverified local-only records, unknown fields,
  private-looking sanitized strings, unexpected files, symbolic links inside a
  release, and hash mismatches all stop the workflow.
- A failed build writes only to a randomly named staging directory and removes
  that staging directory before returning.
- Releases are never deleted automatically. Remove obsolete release directories
  only after confirming they are neither active nor needed for rollback.
- The publisher never logs the source snapshot or retained record values.

## Test

The Dockerized test suite exercises sanitization, tamper detection, deterministic
release creation, HTTP retrieval, update activation, and rollback:

```bash
docker run --rm -v "$PWD:/repo:ro" -w /repo node:22-slim \
  node --test prototypes/operations-dashboard/tests/*.test.mjs
```
