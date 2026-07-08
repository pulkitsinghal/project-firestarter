# {{ project_name }} — opt-in git hooks

These hooks live in `.githooks/` (version-controlled) instead of `.git/hooks/`.
To activate them in your local checkout, run:

```
make hook-install
```

which is shorthand for:

```
git config core.hooksPath .githooks
```

To deactivate:

```
git config --unset core.hooksPath
```

Skip an individual hook invocation with `--no-verify`:
- `git commit --no-verify`
- `git push --no-verify`

## Hooks installed

### `pre-commit`
Runs `make precommit` (all lint/type/test gates, inside Docker — no host SDKs)
when the staged diff touches source. Blocks the commit on failure. Skipped on
docs-only changes.

### `commit-msg`
Validates the in-progress commit subject against the same Conventional Commits
regex as CI (`.github/workflows/commit-lint.yml`). Blocks on invalid subject.
Allowed types: `feat fix refactor chore docs test ci build`. Subject
description must be 1-100 chars. Skips merge / revert / fixup / squash commits.

### `pre-push`
Non-blocking. Prints how many commits ahead of `origin/master` the current
branch is. Does NOT call any reviewer; the GitHub Action handles that.

## Why opt-in
Different contributors prefer different local guardrails. Offering hooks
ready-to-install respects choice while making the common path one command.
