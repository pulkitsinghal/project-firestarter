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

## Response convention — end every response with the URLs

**Every response ends with a short "Links" footer** so the owner never has to
hunt for where the code and the running app live. Include:

- **Repo:** https://github.com/{{ github_owner }}/{{ github_repo }}
- **Every environment that is actually live** — local / dev / qa / staging / prod
  — with its URL (the app and/or its dashboard), read from the table below.

Only list URLs that exist; never invent one for an environment that isn't
deployed yet. Treat a missing footer like a missing test — it's a hard
convention, not a nicety. Keep it to the links, one short block at the end.

### Environments & URLs (single source of truth — keep current)

| Env | App URL | Dashboard / ops URL | Notes |
|-----|---------|---------------------|-------|
| local | _the running app, e.g._ `http://localhost:{{ port_web }}` | — | `make up` |
| dev | _not deployed_ | — | |
| qa | _not deployed_ | — | |
| staging | _not deployed_ | — | |
| prod | _not deployed_ | — | |

> This table is the one place these URLs live. When you stand an environment up
> (`make deploy`, a Cloudflare/Pages deploy, a hosted dashboard, …), record its
> URL here **in the same PR** — `CLAUDE.md` and any status doc point back here.

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

## Local TLS and certificate authority

Read [docs/LOCAL_TLS.md](docs/LOCAL_TLS.md) before changing local HTTPS. Reuse
the owner's canonical workstation CA and reverse proxy recorded in
`~/.config/pet-projects/local-tls.json`; never create a per-project root or
unrelated self-signed certificate. Agents configure routes, while the shared CA
service signs certificates and retains all private keys. Trust-store changes,
CA rotation, and live proxy reloads are owner-approved host operations. Verify
HTTPS without `-k`, `--insecure`, or disabled certificate checks.

## Commit, branch, and merge workflow

### Branching
- `master` is always green and deployable. Never push directly to it.
- One feature/fix per branch; short-lived (≤ 2 days).
- Name: `<type>/<scope>-<slug>` — e.g. `feat/backend-prayer-session`,
  `fix/state-seq-guard`.
- **Parallel sessions → use a git worktree (disk permitting).** When more than
  one session/agent may touch this repo at once, give each its own worktree on
  its own branch instead of sharing one checkout. Each worktree is an isolated
  working tree + index, so concurrent sessions never clobber each other's
  uncommitted changes or fight over branch switches — the main conflict-avoidance
  win:
  ```bash
  git worktree add ../worktree-<slug> -b <branch> origin/master   # isolated checkout
  git worktree remove ../worktree-<slug>                          # clean up when done
  ```
  The `.git` history is shared — only the working files are duplicated — so it
  costs ~one extra checkout per worktree. Prefer this whenever you expect
  parallel work **and have the disk space**; on a tight disk, fall back to
  sequential branches in a single checkout.
- **Stage explicit paths; never blanket-add on a shared checkout.** `git add -A`
  / `git add .` / `git commit -a` sweep *everything* in the tree — including a
  concurrent session's uncommitted work — into your commit. Stage the exact
  files you touched and read `git status` before committing. `.claude/` ships
  deny-rules for the blanket forms plus a SessionStart hook that warns on a dirty
  tree (Claude Code); the norm holds for every tool.
- **Owner-gated work → hand it off as a labeled issue, don't block.** Some steps
  are owner-only — prod credentials, prod-DB migrations, deploys, billing (see
  [docs/DEPLOY_POLICY.md](docs/DEPLOY_POLICY.md)). When you hit one, don't stall
  or bury the ask in chat: open a **self-contained GitHub issue** whose body is a
  copy-paste runbook — exact commands, a verify step, done-criteria checkboxes —
  that the owner (or a session that holds the creds) can execute cold, and label
  it `owner-action`. That turns every hand-off into a filterable queue:
  ```bash
  gh label create owner-action --color 1d76db \
    --description "Needs the owner (prod creds / deploys)" 2>/dev/null || true
  gh issue create --label owner-action --title "…" --body-file runbook.md
  gh issue list --label owner-action --state open   # the live hand-off queue
  ```
  Reuse an existing `owner-action` issue if one already tracks the task instead of
  filing a duplicate.

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

### End-to-end completion loop
Unless the user explicitly narrows the task, completion means the whole safe
lifecycle—not merely “code written.” This sequence defines the desired end
state; it does not create missing authority. Stop at the applicable boundary
when the user has not authorized repository delivery, an owner-only action is
required, or the user-test hold in the push policy applies:

1. Create an isolated worktree + feature branch and record acceptance, data,
   security, migration, deployment, and rollback implications.
2. Implement the smallest maintainable change with tests; run `make precommit`,
   inspect the complete diff, and stage only explicit reviewed paths.
3. When repository delivery is authorized and no user-test hold applies, commit
   conventionally, push the feature branch, and open a self-contained PR with
   the evidence bundle below.
4. Obtain code review and green CI. Resolve findings with new commits; never
   weaken a gate to make the PR pass.
5. When merge is authorized, squash-merge through the PR, update local `master`
   with a fast-forward, then rerun the affected tests plus a proportionate
   post-merge smoke/E2E check.
6. Deploy only when [the deploy policy](docs/DEPLOY_POLICY.md) permits it. Verify
   the live artifact immediately. If that check fails, redeploy the previous
   known-good app or revert the merge; production data/schema rollback follows
   the separate forward-only migration runbook.
7. Record the result and residual risk, then remove the merged worktree and
   delete the merged branch. Never declare success without the test, review,
   merge, and (when applicable) live evidence.

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

### Hermetic unit tests (a precept)

The default unit suite must run with **no network and no secrets** — `make test`
green on a fresh clone with nothing configured. Three idioms make that hold in
any language:
- **Construct SDK/API clients lazily**, inside the call site (and cache them),
  never at module import — importing a module must not require an API key.
- **Guard `listen()`/servers behind a run-directly check** and export the app,
  so importing it for a test never binds a port.
- **Route on-disk state through one env-overridable dir** (e.g. `DATA_DIR`), so
  tests isolate into a temp dir and tear down.

Tests that genuinely need a real DB/network are the exception — gate them behind
a marker + an env var (see the stack's integration-test split) so they self-skip
by default.

### Unique check names

`auto-merge.yml` matches required checks by their job **display name**. If you
add a workflow, give its jobs names that don't collide with `Tests` /
`Lint & Typecheck` / `Build` / `Conventional Commits` / `Secret Scan` — a
duplicate display name shadows the real check in the lookup and can let a PR
merge on the wrong job's result.

## Storyboard — keep it current (a precept)

This project documents itself with a **planned-vs-implemented** storyboard:
`docs/STORYBOARD.md`, auto-generated by the harness in `storyboard/` from real
screenshots of the running app (see `docs/storyboard-harness.md`).

- When you add or change a user-facing screen/flow, update
  `storyboard/manifest.json` and regenerate: `make storyboard`.
- Treat the storyboard as a first-class doc, not an afterthought — it's how the
  team and any AI agent see, at a glance, what's real vs. still planned.
- `.github/workflows/storyboard.yml` refreshes it in CI (non-blocking). Don't
  remove or bypass the harness; keep it green.

## Feature handoff to a user or developer (a precept)

A feature is not ready for handoff when the code merely passes tests. Follow
[docs/FEATURE_HANDOFF.md](docs/FEATURE_HANDOFF.md) and provide an evidence
bundle that the receiver can understand without reconstructing the behavior
from a diff:

1. Exercise the rebuilt app through the acceptance path and at least one
   meaningful failure, retry, rollback, or cleanup path; record exact automated
   and live checks and check the browser console when applicable.
2. For a user-visible change, update the storyboard manifest/driver and promote
   the chosen real-app frames into the committed storyboard doc/assets.
3. Include a compact Mermaid state/flow map covering initial, success, failure,
   retry, and cleanup states when a lifecycle exists. Explicitly mark truly
   stateless work as such.
4. Run the repository's end-user E2E/release rehearsal when one exists and use
   its real captures/recordings as the evidence source.
5. For a material multi-step UI flow, prepare a **20–40 second narrated and
   captioned release cut** when this repository ships a reproducible Dockerized
   recipe and named Make target. Use a natural conversational voice, subtitles,
   and restrained focus/transition effects synchronized to the exact control or
   state being discussed. Commit a compact polished master and optional GIF
   preview under `docs/media/` when each is under 10 MB; use a release attachment
   or Git LFS above that threshold, while raw E2E recordings remain artifacts.
   Keep E2E assertions at normal speed: capture asserted story beats and focus
   targets without `slowMo` or fixed presentation waits, then add voice, captions,
   pacing, and effects in a separate post-process after the tests pass.
   Otherwise mark video N/A and provide an ordered still-frame walkthrough; do
   not improvise a host media toolchain.
6. Make the final handoff self-contained: outcome, screens, state-map
   walkthrough, conditional release cut/N/A rationale, exact verification,
   known limits, rollback, and the next action that requires user authority.

Do not manufacture UI evidence for backend-only or otherwise non-visual work.
Mark visual artifacts N/A with a reason and substitute concise request/response,
log, migration, build/output, or state-transition evidence. Use synthetic/test
fixtures; never put credentials, secrets, private records, or production data
in handoff screenshots, captions, recordings, fixtures, or logs.

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
> - **Keep the storyboard current** — UI changes update `storyboard/manifest.json`
>   and regenerate `docs/STORYBOARD.md` via `make storyboard`.

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
- Storyboard harness: `docs/storyboard-harness.md` → `docs/STORYBOARD.md`
- Feature handoff evidence: `docs/FEATURE_HANDOFF.md`
