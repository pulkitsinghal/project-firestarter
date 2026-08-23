# Mutation testing — prove the test matters

`make mutation-check` is an optional honesty check for important guarantees. It
changes one exact source fragment, proves the focused test passed before the
change and fails after it, then restores the original bytes from a private copy.
It never uses `git checkout`, so pre-existing uncommitted source edits survive.

A new project has no declarations. The command truthfully reports `SKIP` and
exits successfully until the project adds its own load-bearing guarantees to
`scripts/mutation-cases.sh`.

## Add one case

Use a short non-sensitive label, a repository-relative regular file, an exact
fragment that occurs once, its replacement, and a focused test command:

```bash
mutation_case \
  "rejects-expired-session" \
  "src/session.ts" \
  "if (session.expired) return false;" \
  "if (false) return false;" \
  1 \
  -- bash scripts/prove-expired-session.sh
```

The focused adapter must be hermetic, bounded by its own test runner, and select
a named guarantee rather than the entire suite. It runs once with
`MUTATION_CHECK_PHASE=baseline` and once with `MUTATION_CHECK_PHASE=mutant`. In
the mutant phase only, it must recognize the intended named assertion failure
and then write the exact value of `MUTATION_CHECK_EVIDENCE_MARKER` to
`MUTATION_CHECK_EVIDENCE_FILE`. Do not write evidence for a load, syntax,
configuration, timeout, or unrelated test failure.

The number before `--` is the adapter's expected assertion-failure exit status
(1–123). A killed mutant requires both that exact status and the private evidence
file; either signal alone is an error. Missing commands, timeouts, signals,
surviving descendants, and same-status runner failures therefore cannot
masquerade as killed mutants. Output is held in a private temporary file and
never echoed, so expected failures cannot spill fixtures or credentials into CI.

## Result contract

- `PASS`: every configured baseline passed and every mutant was killed.
- `FAIL` (exit 1): at least one test stayed green under its mutation.
- `SKIP` (exit 0): no project-specific cases are configured yet.
- `ERROR` (exit 2): the harness could not prove the result safely — for example,
  the exact fragment occurred zero or multiple times, the baseline was already
  red, a target escaped the repository or crossed a symlink, another run held
  the lock, the test rewrote its target, or restore/cleanup failed.

The harness accepts only single-link regular files at bounded repository-relative
paths, rejects symlinked components, limits targets to 4 MiB, and serializes
runs. Exact fragments are non-empty single-line byte strings; the implementation
uses Bash plus standard file utilities and invokes no project language SDK.
Tests run in a separate process group with a 300-second default deadline
(`MUTATION_TIMEOUT_SECONDS`, bounded to 1–3600); catchable termination stops that
group before restore, and a surviving descendant makes the result an error. The
EXIT/signal path restores the active target byte-for-byte.

`SIGKILL` and abrupt harness-process loss cannot run a trap. For those cases,
`.mutation-check.lock/` is a private, gitignored recovery journal containing the
exact pre-run bytes. It is not a guarantee against sudden storage or filesystem
failure. The next run clears the journal when the target already
matches the original, or restores automatically when the target is still the
recorded mutant (or missing during an interrupted restore). If a test or
editor changed it to a detected third state, the harness preserves both
versions and reports `recovery-required`; reconcile the target with
`.mutation-check.lock/original`, then remove the lock directory. It never silently
overwrites unrecognized drift. After an uncatchable stop, a still-live recorded
child process group blocks recovery. Once an operator proves a conservatively
reported group has ended, remove only `.mutation-check.lock/child_pgid` and rerun.

The run lock serializes this harness; it does not freeze an editor or defend
against a hostile local process racing filesystem operations. Do not edit,
rename, or delete configured targets or their parent directories while the check
runs. Detected drift fails closed, but this optional local tool is not a security
boundary against an adversarial account with write access to the repository.

This check is intentionally not part of `test`, `precommit`, or required CI:
mutation cases are slower periodic evidence, while normal gates remain the fast
merge contract. Add a scheduled or manual workflow only when the project has
real cases and has measured their runtime.
