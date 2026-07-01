# AGENTS.md

This file is the standing brief for any AI agent (Claude Code, Codex, Cursor,
Aider, etc.) starting a session in this repository. It is the *single source of
truth* for how to work here. Humans, see also `CONTRIBUTING.md`.

> Scaffolded from **project-firestarter**. Fill in the project-specific parts
> (the "Project at a glance" summary, domain invariants, and adding-things
> recipes) as the project takes shape.

## Project at a glance

**{{ project_name }}** — {{ project_tagline }}

Layout (see `ARCHITECTURE.md` for the full picture):
- `backend/` — server + database + forward-only SQL migrations.
- the client app (`frontend/`, `app/`, and/or `splash/` depending on the stack).
- `docs/` — product spec, architecture notes, open questions.

## Session startup checklist

Run these every time you open a new session, in order. Do not skip.
1. `git fetch --all --prune` and `git --no-pager status` — know the branch state.
2. `git --no-pager log --oneline -10` — read recent commits for current intent.
3. If `master` is behind `origin/master`, fast-forward (`git pull --ff-only`)
   before doing anything else.
4. Read the current versions of `ARCHITECTURE.md`,
   `PROJECT_STATUS_AND_NEXT_STEPS.md`, and the newest entries in
   `backend/migrations/`.
5. List Docker state: `docker compose ps` so you know whether the stack is up.

## Commit, branch, and merge workflow

### Branching
- `master` is always green and deployable. Never push directly to it.
- One feature/fix per branch; short-lived (≤ 2 days).
- Name: `<type>/<scope>-<slug>` — e.g. `feat/backend-prayer-session`,
  `fix/state-seq-guard`.
- For parallel work, each agent gets its own git worktree on its own branch:
  `git worktree add ../worktree-<slug> -b <branch> origin/master`.

### When to commit
Commit at the smallest unit of work that leaves the tree in a revert-worthy
state:
- Feature/fix complete, all gates green.
- A migration applied (DB schema is its own commit, never bundled with code that
  uses it).
- Before a risky refactor: commit current working state first.
- Never commit broken intermediate state on `master`. On a feature branch it's
  fine; squash on merge.

### Commit messages
Use **Conventional Commits**:
```
<type>(<scope>): <imperative subject, ≤72 recommended, 100 enforced>

<body explaining *why*, not *what* — optional, only when not obvious>
```
`.github/workflows/commit-lint.yml` rejects subjects whose description exceeds
100 characters. Types: `feat fix refactor chore docs test ci build`. Scopes:
`{{ commit_scopes }}`. Template: `.gitmessage`
(`git config --local commit.template .gitmessage`).

{{ coauthor_policy }}

### Pull requests
- Always via PR, even solo. CI must be green.
- Squash-merge into `master`. The PR's conventional-commit subject becomes the
  trunk commit.
- Rebase, never merge, when pulling `master` into a feature branch.
- Delete the branch after merge.

### Push policy
- **Push feature branches by default** once local gates pass.
- **Exception: user test pending.** Hold the branch local when the change
  includes something only the user can verify on their machine (a UI change, an
  OS-specific step). Tell the user what to test and what command to run, then
  wait for their go-ahead.
- **Never push to `master` directly.** Always via a feature branch and PR.

### Never
- **Never commit without explicit user approval** (unless they delegated a chunk
  of work with implicit commit authority).
- **Never force-push** a shared branch.
- **Never edit an applied migration** unless the edit is provably idempotent
  (`IF NOT EXISTS` guards). Otherwise add a new numbered migration. To *undo*
  one, write a revert migration — see [docs/migration-rollback.md](docs/migration-rollback.md).

## Engineering gates

These run in CI (`.github/workflows/ci.yml`) and are the self-review bar for any
commit. One-shot local equivalent — run before staging:
```
make precommit
```
which runs every lint / type-check / test gate, all inside Docker.

## AI code review

1. **Pre-commit self-review** — the gates above + read your staged diff back.
2. **Automated PR review on GitHub** — `ai-pr-review.yml` calls the Anthropic API
   and posts a BLOCKING / NON-BLOCKING / LGTM verdict. Auto-merge respects it.
   Requires the `ANTHROPIC_API_KEY` secret — never paste it in chat/PRs/commits;
   set it via `gh secret set` (see `docs/ci-secrets.md`).

## Domain invariants (do not violate)

> Fill these in. Every project has a small set of rules that must hold no matter
> what. Examples from sibling projects:
> - **Forward-only, idempotent migrations.** `migrations/NNN_name.sql`.
> - **No host SDKs** — every toolchain is a profiled Docker Compose service.
> - A single canonical write path for the core domain entity (don't re-implement
>   it client-side).

## Toolchain notes — principle: no host SDKs

Every language toolchain is a profiled Docker Compose service, not a "please
install on your host" line. The dev experience is `make <task>`; under the hood
it is `docker compose --profile <p> run --rm <svc> ...`.

Adding a toolchain means: add a profiled Compose service, pin the image, add
`make` targets, and update this file plus `CLAUDE.md`.

## Cross-references
- Architecture & layers: `ARCHITECTURE.md`
- Phases & current status: `PROJECT_STATUS_AND_NEXT_STEPS.md`
- Open questions / decisions: `docs/OPEN_QUESTIONS.md`
- CI secrets: `docs/ci-secrets.md`
