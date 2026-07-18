# Contributing

Humans and agents share one workflow. The authoritative engineering brief is
[AGENTS.md](AGENTS.md); this is the short version.

## Setup

You need Docker. Nothing else — no host Python, Node, Dart, or psql.

```
make up            # start the stack
make migrate       # apply migrations
make hook-install  # activate the opt-in git hooks
```

## Before you commit

```
make precommit
```

runs every lint / type-check / test gate, all in Docker. A green run is a good
predictor of green CI.

For a fast self-review before opening the PR, pipe your diff into a review chat:

```
bash scripts/ai-review.sh        # prints diff vs origin/master + a reviewer prompt
```

## Commits

Conventional Commits, enforced by the `commit-msg` hook and CI:

```
<type>(<scope>): <subject ≤72 chars recommended, 100 enforced>
```

Types: `feat fix refactor chore docs test ci build`. Scopes:
`{{ commit_scopes }}`.

{{ coauthor_policy }}

## Pull requests

- Branch off `master`, one feature/fix per branch.
- Open a PR; CI must be green. The AI reviewer posts a verdict; auto-merge
  squash-merges when all checks pass.
- Rebase (don't merge) when pulling `master` into your branch. Delete the branch
  after merge.

## Before handing a feature to a user or developer

Use [docs/FEATURE_HANDOFF.md](docs/FEATURE_HANDOFF.md). A visible UI feature
ships to review with real rebuilt-app storyboard frames, a compact state map,
and exact acceptance/failure/verification evidence. A short captioned release
cut is expected for a material multi-step flow only when the repository provides
a reproducible harness; use any full E2E rehearsal as its source, and include a
natural voice, subtitles, and restrained focus effects. Commit compact polished
media under `docs/media/` when each file is under 10 MB; keep raw recordings as
CI artifacts and use a release attachment or Git LFS for larger masters.
Do not slow assertions for presentation: capture stable E2E story beats at normal
speed, then add narration, captions, pacing, and focus effects after the run.
Otherwise mark it N/A and provide a still walkthrough.
For non-visual work, mark UI artifacts N/A and provide equivalent API, log,
migration, build/output, or state-transition evidence.

## The rules that matter most

- Migrations are forward-only and idempotent. Never edit an applied migration.
- Every toolchain runs in Docker — never install SDKs on the host.
- User/dev handoffs include inspectable evidence, not only a prose claim that
  the feature is done.

See [ARCHITECTURE.md](ARCHITECTURE.md) for why.
