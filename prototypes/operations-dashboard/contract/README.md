# Dashboard contract

`dashboard-state.schema.json` defines the shared structural contract.
`dashboard-state.sample.json` is the sole committed fixture.
`validate-dashboard.mjs` provides dependency-free validation for build and test
harnesses.

## Surface rules

### Native

- Reads an optional file from its own sandboxed Application Support container.
- Accepts generic, sanitized, and locally verified records.
- Rejects every `local-only` record unless its verification is `verified`.
- Owns foreground, pinning, close, and reopen behavior.
- Keeps window controls and local file provenance in its private adapter rather
  than adding those capabilities to the shared snapshot.
- Performs no network access or telemetry transmission.

### Web

- Reads a snapshot that was sanitized before it entered the web build or
  deployment process.
- Accepts `sanitized-remote` snapshots only.
- Rejects every `local-only` record and every private-looking string.
- Has no endpoint, connection, URL, host, or local-path field in the contract.
- Must not poll, proxy, or bridge to the native app or its state file.

The resource-budget array describes operational scheduling lanes, not
operating-system measurements. Numeric `value` and `capacity` fields are
optional. The committed shared fixture omits them rather than claiming live
capacity or telemetry.

Queue records may add the optional, privacy-neutral evidence fields
`completedSteps`, `totalSteps`, `currentStep`, `lastActiveSeconds`, `memoryMB`,
and `cpuPercent`. The two step counts must appear together and completed work
cannot exceed the current total. Increasing the total may therefore lower the
derived completion percentage without erasing completed work. Consumers must
treat missing evidence as unavailable rather than estimating it. These
additive fields preserve compatibility with version `1.0` records that omit
them.

## Canonical shape

The root keys are exactly `schemaVersion`, `mode`, `queue`, `tests`,
`resourceBudget`, and `signals`. Version `1.0` replaces the earlier draft names
`snapshotKind` and `qualityChecks`; it also replaces a singular resource-budget
object and the queue state `next`. Consumers must not accept those draft aliases.
