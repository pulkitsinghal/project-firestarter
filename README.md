# Project Firestarter

A version-controlled **starter template** for new sibling projects. It distills
the shared developer- and devops-level scaffolding from the existing projects
([project-pilgrim](../project-pilgrim) and [project-healer](../project-healer))
into one place so a new repo starts with all the best practices, gotchas, and
nice-to-haves already wired in — not rediscovered each time.

It's **cookiecutter-style**: a [`firestarter.config.json`](firestarter.config.json)
manifest declares the variables, and a generator stamps a new project by
substituting `{{ tokens }}` into the templates. The generator runs **in Docker**
(`python:3.12-slim`) so nothing is installed on your host — the same "no host
SDKs" rule the templates themselves enforce.

## What you get

- **Universal meta-layer** (`template/`) — identical across every sibling:
  governance docs (`AGENTS.md`, `CLAUDE.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`,
  `PROJECT_STATUS_AND_NEXT_STEPS.md`), opt-in git hooks, the conventional-commit
  toolchain, and the full CI/CD suite — **AI PR review**, **auto-merge**,
  **commit-lint**, and a **Playwright storyboard**.
- **Two ready stack profiles** (`stacks/`):
  - `fastapi-next` — FastAPI + PostgreSQL/pgvector + Redis backend, Next.js
    frontend (the project-healer lineage).
  - `supabase-flutter` — Postgres/PostGIS + PostgREST + GoTrue backend, Flutter
    app, React/Vite splash, Dart service layer (the project-pilgrim lineage).

See [docs/ANATOMY.md](docs/ANATOMY.md) for a file-by-file map of what each piece
is, why it exists, and which sibling it was lifted from.

## For AI agents

This repo is built to be handed to an AI session of any kind. Drop a Claude Code,
Codex, Cursor, Aider, or Copilot session into it and it will find its operating
brief in **[AGENTS.md](AGENTS.md)** (the cross-tool standard) — how to stamp a new
project, how to extend the template, and the hard rules (no host SDKs, whitelist
token safety, the CI job-name contract). `CLAUDE.md` and
`.github/copilot-instructions.md` are thin pointers to it.

## Usage

```bash
# Interactive — prompts for every value (Enter accepts the default):
./bin/firestart.sh

# Non-interactive — accept all defaults:
./bin/firestart.sh --defaults

# Override specific values:
./bin/firestart.sh --set project_name="Project Lighthouse" \
                   --set project_slug=lighthouse \
                   --set stack=supabase-flutter \
                   --output ../project-lighthouse

# Or feed a JSON answers file:
./bin/firestart.sh --values my-answers.json
```

The generator writes a new project to `../<github_repo>` (override with
`--output`) and prints the next steps:

```bash
cd ../project-lighthouse
git init && git add -A && git commit -m "chore: scaffold from firestarter"
make hook-install
make up && make migrate
gh secret set ANTHROPIC_API_KEY   # enable the AI PR reviewer
```

## Configuration

Every key in [`firestarter.config.json`](firestarter.config.json) is a template
token. List values are multiple-choice (first = default); string values can
reference earlier answers (e.g. `db_name` defaults to `{{ project_slug }}`). The
generator also computes a few derived tokens (`migrations_table`,
`coauthor_policy`, …) — see [docs/ANATOMY.md](docs/ANATOMY.md#tokens).

## Keeping it current

This template is meant to **absorb learnings over time**. When a sibling project
discovers a better hook, a CI fix, or a new gotcha worth standardizing, lift it
back here. The process is in [docs/LIFT-LOG.md](docs/LIFT-LOG.md). Adding a whole
new stack profile is in [docs/ADDING-A-STACK.md](docs/ADDING-A-STACK.md).
