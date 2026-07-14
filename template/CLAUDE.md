# {{ project_name }} — Claude Code Context

## What this project is

{{ project_tagline }}

> Scaffolded from **project-firestarter**. Expand this section with the product
> thesis and the one architectural rule that defines the system.

## Architecture at a glance

```
backend/    server + database + forward-only migrations
            migrations/   forward-only NNN_*.sql
the client app (frontend/ and/or app/ and/or splash/ — stack-dependent)
docs/       product spec, architecture notes, open questions
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full layer rules.

## Session startup checklist

1. Read `PROJECT_STATUS_AND_NEXT_STEPS.md` — current MVP scope and what's done.
2. Read `docs/OPEN_QUESTIONS.md` — known gaps and deferred decisions.
3. Read `AGENTS.md` — engineering workflow, commit format, push policy.

## Owner preferences (read before doing anything)

- **No host toolchains.** Language SDKs (Python, Node, Dart, psql, …) belong in
  Docker Compose profiles. Never install them on the host. Run checks via the
  Makefile (`make help` lists every target):
  - All CI gates locally: `make precommit`
  - Tests: `make test`
  - Migrations: `make migrate`
  - Storyboard screenshots: `make storyboard`
- **Validate locally before pushing.** Run `make precommit` via Docker before
  every push. Never push speculatively to see if CI catches it.
- **Hand features over with evidence.** Follow
  [docs/FEATURE_HANDOFF.md](docs/FEATURE_HANDOFF.md): every change needs exact
  acceptance, failure/recovery, and verification evidence. Visible UI work adds
  real storyboard frames and a state/flow map. Add a short captioned release cut
  for material multi-step flows only when a reproducible repository harness
  exists; otherwise mark it N/A and provide a still walkthrough. Use synthetic
  data in every handoff artifact.
- **AI-reviewed PRs, no human review required.** PRs go to `master`.
  `ai-pr-review.yml` calls the Anthropic API directly (requires
  `ANTHROPIC_API_KEY` repo secret) and posts a verdict comment. Auto-merge
  triggers on LGTM/NON-BLOCKING. **Never paste secret values into chat/PRs/commits**
  — set them via `gh secret set`; see [docs/ci-secrets.md](docs/ci-secrets.md).
- **Conventional commits, required.** `type(scope): subject`. Types:
  `feat fix refactor chore docs test ci build`. Subject ≤ 100 chars.
- **Forward-only migrations.** Never edit an applied migration except for
  provably idempotent `IF NOT EXISTS` hardening. New behaviour = new numbered file.
- **One local CA, no agent-held signing keys.** Before changing local HTTPS, read
  `docs/LOCAL_TLS.md` and the host's `~/.config/pet-projects/local-tls.json`.
  Reuse the canonical proxy/CA; never create a project root or persist a TLS
  verification bypass.
- **Stage explicit paths, never `git add -A`.** This checkout may be shared by
  concurrent sessions; blanket staging sweeps another session's work into your
  commit. `.claude/settings.json` denies the blanket forms — see *Branching* in
  [AGENTS.md](AGENTS.md).
- **End every response with the Links footer.** The repo URL
  (`https://github.com/{{ github_owner }}/{{ github_repo }}`) + every live
  environment/dashboard URL — see *Response convention* and the *Environments &
  URLs* table in [AGENTS.md](AGENTS.md). Record new environment URLs there the
  moment they go live.

## Domain invariants (non-negotiable)

> Fill these in — the rules that must always hold. Universal starters:
1. **Forward-only, idempotent migrations.** `migrations/NNN_name.sql`.
2. **No host SDKs** in Compose profiles.
3. A single canonical write path for the core domain entity; never re-implement
   it client-side.

## Stack notes that save time

- **Migrations** are applied by `bash backend/scripts/migrate.sh` (tracked in
  `{{ migrations_table }}`). They are **not** auto-applied on container start —
  run `make migrate` after `make up`.
- **Tooling runs in containers** behind Compose profiles. The app services run
  by default; lint/type/test toolchains live behind profiles invoked by the
  Makefile.
- **Host ports are offset** (db {{ port_db }}, redis {{ port_redis }},
  api {{ port_api }}, web {{ port_web }}) so this stack coexists with other
  local Docker stacks.

## CI checks on every PR

| Check | What it runs |
|-------|-------------|
| Conventional Commits | commit subject format |
| Lint & Typecheck | linters + type-checkers in Docker |
| Tests | compose up → migrate → test suite in a tools container |
| Build | production build of the client (path-gated) |
| Claude PR review | Direct Anthropic API call; posts verdict comment |
| Auto-merge if green | squash-merges when all checks pass and verdict is not BLOCKING |

## Key files

| File | Purpose |
|------|---------|
| `ARCHITECTURE.md` | Layers, data model, invariants |
| `PROJECT_STATUS_AND_NEXT_STEPS.md` | MVP phases, what's done, what's next |
| `docs/OPEN_QUESTIONS.md` | Deferred decisions and known gaps |
| `docs/ci-secrets.md` | How to provide CI secrets without leaking them |
| `docs/FEATURE_HANDOFF.md` | Evidence bundle for user/dev feature review |
| `Makefile` | All common dev commands (`make help`) |
| `backend/migrations/` | Forward-only SQL migrations |
