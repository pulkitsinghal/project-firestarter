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
First checks the complete proposed message for automatic issue-closing
directives, including comment-looking lines and merge / revert / fixup / squash
messages. This conservative superset is necessary because editor, `-m`, and
verbatim cleanup modes retain different lines. Closure intent belongs only in
the PR template's final `Issue closure` section; number ordinary prose as
`Fix 1`. Then validates the subject against the same Conventional Commits regex as CI
(`.github/workflows/commit-lint.yml`). Allowed types: `feat fix refactor chore
docs test ci build`; the description must be 1-100 chars. Machine-generated
subjects skip only that second regex check.

### `pre-push`
Non-blocking. Prints how many commits ahead of `origin/master` the current
branch is. Does NOT call any reviewer; the GitHub Action handles that.

## Why opt-in
Different contributors prefer different local guardrails. Offering hooks
ready-to-install respects choice while making the common path one command.
