# Bounded runner

Use `tools.bounded_runner` for finite local commands that can outlive an agent
turn: test shards, asset builds, migration checks, or bounded batch work. It
provides four guarantees:

1. Every unit has a wall-clock deadline. A timeout or heartbeat stall is a
   normal, named outcome and terminates the unit's POSIX process group.
2. Units declare `write_paths`; overlapping writers are rejected before any
   command starts and are blocked across separately launched specs.
3. Resume is opt-in and accepts only success or checkpoint evidence bound to
   the exact loaded spec and unit fingerprint.
4. Aggregate coverage is closed-world. A required `MISSING`, `FAIL`, `TIMEOUT`,
   `STALLED`, `BLOCKED`, or `KILLED` unit makes the run exit non-zero. Silence is
   never success.

The spec is trusted operator input. Commands are argv arrays executed with
`shell=False`; shell strings, globbed write paths, path escapes, overlapping
ownership, unknown fields, and malformed state are rejected. A unit receives a
small baseline environment plus only the literals in `env` and names explicitly
allowed through `inherit_env`. Never put secrets in argv, a literal `env`, the
spec, checkpoints, or child output. Child output is captured in private local
state, but the child still owns its own redaction policy.

## Quick start

Copy the example, replace its commands and paths, change the copied
`run.root` from `"../../.."` to `"."`, then run from the project root with the
pinned Docker wrapper. Docker is the only host runtime:

```sh
cp tools/bounded_runner/examples/units.example.toml bounded.units.toml
./scripts/bounded-runner.sh preflight bounded.units.toml
./scripts/bounded-runner.sh run bounded.units.toml
./scripts/bounded-runner.sh status bounded.units.toml
```

The wrapper pins one Linux Python image by digest, drops capabilities, uses a
read-only container filesystem, and mounts only the project root writable. To
pass an explicitly allowlisted host variable into that container without
placing its value in argv, set names only, for example
`BOUNDED_RUNNER_DOCKER_ENV='ASSET_SERVICE_TOKEN'`. The spec must repeat the same
name in `inherit_env`. On a trusted Linux development container that already
has Python 3.11+, the equivalent direct command is
`PYTHONPATH=. python3 -B -m tools.bounded_runner ...`.

`preflight` parses the closed schema and proves the in-spec write partitions
without creating runner state or starting commands. `status` is also read-only.
`aggregate` writes a fresh `run.json`; `run` writes unit records and then the
aggregate. Use `--json` with `status` or `aggregate` for machine consumption.

Use `run --resume` only after inspecting the previous outcome. Resume skips a
unit only when its prior `OK` record has the exact current fingerprint, or its
currently present checkpoint declares completion with that fingerprint. A
checkpoint-derived `SKIPPED` record never authenticates a later skip by itself.
Changing any spec content invalidates earlier evidence.

## Spec contract

```toml
[run]
name = "bounded-checks"
root = "."                 # relative to this spec
state = ".bounded-runner"  # confined under root
worker_budget = 4
poll_interval_s = 0.1

[[unit]]
id = "assets"
cmd = ["python3", "scripts/build_assets.py"]
cwd = "."
write_paths = ["build/assets"]
deadline_s = 900
grace_s = 5
workers = 2
required = true
heartbeat_stall_s = 120
checkpoint = "build/assets/checkpoint.json"
verify = ["python3", "scripts/verify_assets.py"]
verify_deadline_s = 60
inherit_env = ["ASSET_SERVICE_TOKEN"]
input_revision = "asset-input-v1" # opaque/non-secret; rotate when inherited inputs change
```

Set `readonly = true` instead of `write_paths` only when the command and every
descendant genuinely avoid project writes. The declaration is an admission
contract, not a filesystem sandbox. Commands must not daemonize, create a new
session, or deliberately escape their inherited process group.

The scheduler accounts for each unit's `workers` against `worker_budget`.
`deadline_s` always applies. When `heartbeat_stall_s` is present, the child must
atomically touch or replace the path in `RUNNER_HEARTBEAT` as it makes progress.
A stale or missing heartbeat produces `STALLED`.

Any unit using `inherit_env` must declare a non-secret `input_revision`. Change
that opaque revision whenever an inherited input's meaning or value changes;
the revision, never the secret value, is fingerprint-bound so resume cannot
silently reuse output from an earlier input.

When `checkpoint` is present, the child receives `RUNNER_CHECKPOINT` and
`RUNNER_FINGERPRINT`. Write the checkpoint atomically and include either:

```json
{"runner_fingerprint":"value from RUNNER_FINGERPRINT","done":true}
```

or non-negative integer progress where `chunks_total > 0` and
`chunks_done >= chunks_total`. A partial, oversized, unreadable, or
fingerprint-mismatched checkpoint is incomplete and never causes a skip.

## Outcomes and recovery

State is local under `.bounded-runner/`; cross-run admission locks are fixed at
`.bounded-runner-locks/` so changing `run.state` cannot bypass ownership. Both
directories should remain untracked and private. Records do not contain command
argv or environment values. Logs are unique per attempt.

Every stamped project has one tracked `.bounded-runner-root` marker. `run.root`
must resolve exactly to that directory; alternate nested roots are rejected so
two specs cannot split the registry while writing the same physical project.

The runner never guesses that a stale lock is safe. A crashed runner, foreign
host lock, malformed lock, surviving process group, or unverifiable cleanup
remains blocking. Before manually removing a lock, prove the recorded runner and
child process trees have stopped and confirm no other host is using the same
working tree. Do not automate stale-lock deletion.

Status meanings:

- `OK`: command exited zero and optional verification passed.
- `SKIPPED`: explicit resume accepted exact fingerprint-bound evidence.
- `PENDING`: the current invocation has not reached a terminal record; this is
  always incomplete and prevents an older success surviving a crash.
- `FAIL`: command, verification, state handling, or cleanup failed.
- `TIMEOUT`: wall-clock deadline elapsed.
- `STALLED`: the configured heartbeat stopped advancing.
- `BLOCKED`: ownership could not be admitted safely.
- `KILLED`: the runner was interrupted.
- `MISSING`: a declared unit has no exact current record.

Only `OK` and `SKIPPED` satisfy required coverage. Every declared `MISSING`
unit fails coverage even when it was marked optional. An active or stale run
lease also makes standalone `status`/`aggregate` fail.

## Boundaries

This module does not assign tasks, issue leases to agents, manage long-lived
services, publish artifacts, enforce an OS write sandbox, use network APIs, or
store credentials. Keep PM/orchestrator ownership in its own control plane and
service lifecycle in the service-supervisor contract. The bounded runner starts
only explicit one-shot argv from a trusted local spec.
