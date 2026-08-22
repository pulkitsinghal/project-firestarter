# bounded_runner add-on

Opt-in, stack-agnostic execution for finite project jobs that need explicit
deadlines, bounded parallelism, write-path admission, checkpoint-aware resume,
and complete machine-readable coverage.

The add-on is Python-standard-library-only. It overlays
`tools/bounded_runner/`, a pinned `scripts/bounded-runner.sh` Docker wrapper,
and `docs/BOUNDED_RUNNER.md` into every stack when
`include_bounded_runner=yes`; it is absent by default.

This is a local one-shot process runner, not a task owner, daemon, workflow
engine, or service supervisor. Its trusted spec declares argv arrays and the
paths each unit may write. The runner schedules non-overlapping units within a
worker budget, kills a POSIX process group at a deadline or stale heartbeat,
and fails the aggregate when any required unit is silent or unsuccessful.

Version 1 deliberately executes only where POSIX process-group cleanup can be
proved. The wrapper gives Linux, macOS, and Windows/Git-Bash hosts the same
Linux execution path without installing a host Python SDK.

See [`common/docs/BOUNDED_RUNNER.md`](common/docs/BOUNDED_RUNNER.md) for the
operator contract and
[`common/tools/bounded_runner/examples/units.example.toml`](common/tools/bounded_runner/examples/units.example.toml)
for a starter spec.
