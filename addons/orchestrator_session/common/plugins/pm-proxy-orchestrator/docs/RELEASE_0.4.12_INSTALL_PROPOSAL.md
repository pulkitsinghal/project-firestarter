# Release 0.4.12 (control bundle 1.4.11): diagnostic-only install proposal

Status: **proposal only. Do not perform the install from this session.** This is
the owner-terminal runbook for the version-distinct, diagnostic-only release cut
from `ab2a17a`. Its only behavior change over 0.4.11 / 1.4.10 is the allowlisted
`pm_proxy_doctor` diagnostic category. There is no schema migration (state
schema stays `1.4`) and the SQLite authority is never edited or replaced.

## Exact artifact identity

- Plugin version: `0.4.12`
- Control bundle version (`orchestrator-control/VERSION`): `1.4.11`
- State schema: `1.4` (unchanged; no migration)
- Interface: `1.0` (unchanged); bridge `1.4`; ticket `1.3` (all unchanged)
- Pinned runtime identity the pin tool records for this artifact:
  - `control_version = 1.4.11`
  - `runtime_sha256 = 9c7c815db41e28e1d0d00f4be9a1aef1ff7d88184def680547d06260e7d7711b`
    (content digest of the control bundle: CLI, VERSION, `root_role_guard.py`,
    the runtime verifier, and every schema, computed by the algorithm in
    `scripts/configure_runtime_pin.py`)
- Immutable source identity: the release commit on branch
  `claude/firestarter-pm-proxy-diagnostic-3e5004` (the session that prepared this
  reports the exact commit SHA). Verify the extracted source matches it before
  installing; the `runtime_sha256` above must reproduce.

## Prechecks (owner terminal, read-only)

1. Confirm the extracted source is the exact release commit and that
   `orchestrator-control/VERSION` reads `1.4.11` and
   `.codex-plugin/plugin.json` reads `0.4.12`.
2. Recompute `runtime_sha256` from the extracted bundle and confirm it equals the
   value above.
3. Confirm the current live pin and adoption are for `0.4.11` / `1.4.10` (an
   install replaces them; it never edits SQLite).
4. Confirm no covered task is mid-launch that depends on the old pin; this
   release does not change launch/receipt/heartbeat/handback/archive behavior,
   but a version change invalidates the prior pin and adoption by design.

## Install steps (owner terminal)

1. Add or update the repo-local marketplace root and reinstall the plugin by
   name from that marketplace (per `INSTALL_UPDATE_ROLLBACK.md`), then start a
   new Codex task so the skill reloads. Retain the prior `0.4.11` source tree and
   its hashes until this release passes task-level smoke tests.
2. Recreate the runtime pin against the clean `1.4.11` runtime:
   `python3 scripts/configure_runtime_pin.py --project-root <clean-runtime-root>`.
   It writes a mode-`0600` `~/.codex/orchestrator-state/runtime-pin.json`
   recording `plugin_version 0.4.12`, `control_version 1.4.11`, and the
   `runtime_sha256` above. It contains no credential, prompt, task, or
   private-record data.
3. From a hook-untrusted bootstrap task, confirm the typed MCP surface exposes
   the documented tools and run typed `doctor`.
4. Repeat the covered-path proof and record a fresh adoption receipt carrying
   plugin version `0.4.12`. Capacity reconfiguration, launch, close/refill, and
   watchdog-refill stay disabled until both the pin and a current-version
   covered-path adoption exist.

## Expected doctor output

- Healthy state: `pm_proxy_doctor` returns `ok` with `schema_version` `1.4`,
  `runtime_pin.verified` true, `runtime_pin.control_version` `1.4.11`, and
  **no** `diagnostic_category` field (success is unchanged).
- Degraded state access (the new behavior): the tool result is an error with
  `code` `state-fail-closed` and exactly one `diagnostic_category` of
  `database`, `filesystem`, or `unknown`. No raw exception, path, SQL, state,
  secret, or runtime-pin summary is present on failure. A doctor failure that is
  not a state-access fault (for example a quarantined-policy or
  schema-incompatibility failure) carries `diagnostic_category` `unknown`; a
  fault diagnosed before state access (a pin drift or invalid arguments) carries
  no `diagnostic_category` at all.

## Stop conditions

- `runtime_sha256` does not reproduce, or versions do not read `0.4.12` /
  `1.4.11`: stop; the artifact is not the reviewed release.
- The pin command reports drift or a mismatched root: stop; do not relax or
  hand-edit the pin.
- Typed MCP discovery is incomplete or `doctor` fails for any reason other than a
  genuine state fault: stop and keep `0.4.11` / `1.4.10` in place.
- The adoption proof does not pass: stop; leave automatic launch/refill disabled.

## Rollback to 0.4.11 / 1.4.10

Restore the retained `0.4.11` plugin source tree and reinstall the same plugin
name from the marketplace; start a new task. Recreate the runtime pin for the
restored `0.4.11` / `1.4.10` runtime; never copy or relax a mismatched pin.
Because there is no schema migration in this release, no database change is
involved either way.

## SQLite is never edited or replaced

Installing, pinning, adopting, and rolling back this release change only the
plugin source, the content runtime pin, and the adoption receipt. The Firestarter
SQLite authority database is never edited, copied over, rolled back, or replaced
at any step.
