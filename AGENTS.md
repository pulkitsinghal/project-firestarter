# AGENTS.md — operating brief for AI sessions

This file is the standing brief for **any** AI agent (Claude Code, Codex, Cursor,
Aider, Copilot, Jules, …) working in **project-firestarter**. It is the single
source of truth; tool-specific files (`CLAUDE.md`, `.github/copilot-instructions.md`)
just point here.

> Note the two altitudes: this repo *generates* projects. The files under
> `template/` and `stacks/` are **outputs** that contain `{{ tokens }}` and a
> separate `template/AGENTS.md` for the *generated* project. THIS file governs
> work on the generator itself. Don't confuse the two.

## What this repo is

A cookiecutter-style template generator. It distills the shared developer- and
devops-level scaffolding from the sibling projects (project-pilgrim,
project-healer) so a new repo starts with the best practices already wired in.
Read [README.md](README.md) and [docs/ANATOMY.md](docs/ANATOMY.md) first — ANATOMY
is the file-by-file map of what everything is and where it came from.

## The two jobs you'll be asked to do

### 1. Stamp a new project
```bash
./bin/firestart.sh                                   # interactive
./bin/firestart.sh --values examples/healer.answers.json --output ../project-x
./bin/firestart.sh --defaults --set stack=supabase-flutter --set project_slug=foo
```
The generator overlays `stacks/<stack>/` on `template/`, substitutes
`{{ tokens }}`, and writes to `../<github_repo>` (or `--output`). It then prints
the next steps (git init, `make hook-install`, `make up && make migrate`,
`gh secret set ANTHROPIC_API_KEY`).

### 2. Improve the template (lift a learning back)
When a sibling project finds a reusable CI fix, hook, or gotcha, fold it in.
Follow [docs/LIFT-LOG.md](docs/LIFT-LOG.md): generalize with tokens, place it in
`template/` (universal) or `stacks/<stack>/` (stack-specific), document gotchas
as inline comments, add a row to `docs/ANATOMY.md` and the lift log.
Adding a whole new stack: [docs/ADDING-A-STACK.md](docs/ADDING-A-STACK.md).

## Hard rules (do not violate)

1. **No host SDKs.** The generator runs in Docker (`bin/firestart.sh`); never
   `pip install` or run language toolchains on the host. The escape hatch
   `FIRESTARTER_NATIVE=1` is for CI images only.
2. **Token safety.** Substitution is **whitelist-only** — every key in
   `firestarter.config.json`. Never broaden it to "replace any `{{ }}`": GitHub
   Actions `${{ … }}` and JSX `style={{ … }}` MUST pass through untouched. If you
   add a token, add it to the config, not to a regex.
3. **Both stacks must keep stamping cleanly.** After any change, re-run the
   verification below for *both* example answer files.
4. **CI job-name contract.** Generated `ci.yml` job display names must stay
   `Tests` / `Lint & Typecheck` / `Build` — `auto-merge.yml` gates on them.
5. **Tokens, not literals, in `template/` and `stacks/`.** Use
   `{{ project_name }}`, `{{ db_name }}`, ports, etc. Filenames may carry tokens
   too (e.g. `{{ project_slug }}_services.dart`).
6. **Storyboarding is a precept, not an optional extra.** Every stack must ship a
   working storyboard harness — `storyboard/` + the `storyboard` Compose profile +
   `make storyboard` + `.github/workflows/storyboard.yml` — that renders the
   *planned-vs-implemented* map (`docs/STORYBOARD.md`) from real screenshots of the
   running app. A project documenting itself is one of firestarter's merits; don't
   drop it, hide it behind a flag, or let a stack regress it. New stacks
   ([docs/ADDING-A-STACK.md](docs/ADDING-A-STACK.md)) must wire their own.

## Verify before you commit

Run the generator in Docker for both stacks and check nothing leaked:

```bash
SB=$(mktemp -d)
for ex in healer pilgrim; do
  docker run --rm -v "$PWD:/gen:ro" -v "$SB:/out" -w /gen python:3.12-slim \
    python /gen/bin/generate.py --values /gen/examples/$ex.answers.json --output /out/$ex
done
# No unsubstituted tokens (JSX style={{ }} is the only allowed match):
grep -rn '{{' "$SB" | grep -vE '\$\{\{|style=\{\{' || echo "✓ no leaks"
# GitHub expressions preserved:
grep -c '\${{' "$SB/healer/.github/workflows/auto-merge.yml"
```

Then sanity-check generated shell (`bash -n .../migrate.sh`), and that
`bin/generate.py` compiles (`python -m py_compile`).

## Commit & PR conventions (this repo)

- **Conventional Commits**: `type(scope): subject` (≤100 chars). Scopes:
  `template stacks bin docs ci build`.
- Branch off `master`; open a PR; squash-merge. Don't push straight to `master`.
- This repo runs the same CI it ships: `ci.yml` (Tests + Lint & Typecheck),
  `commit-lint.yml`, `ai-pr-review.yml`, `auto-merge.yml`. Label a PR
  `auto-merge` and it squash-merges once checks are green and the AI verdict
  isn't BLOCKING. Real reviews need the `ANTHROPIC_API_KEY` secret; without it
  the reviewer degrades to a NON-BLOCKING stub.
- `master` has **lenient branch protection** (free-tier friendly): required
  checks `Tests` / `Lint & Typecheck` / `Conventional Commits`, **0 required
  approvals** (no human reviewer — the AI review + auto-merge gate instead),
  admins exempt, no strict/up-to-date requirement.

### Free-account note
Branch protection and required checks are free on **public** repos but need a
paid plan on **private** ones. The `auto-merge.yml` workflow doesn't depend on
branch protection — it merges via the API based on its own check + verdict
logic — so generated projects auto-merge even on free private repos. Branch
protection just enforces the same rules server-side when available. Don't make
any generated stack *require* a paid feature to function.

## Map
- [README.md](README.md) — overview + usage
- [docs/ANATOMY.md](docs/ANATOMY.md) — file-by-file map, token reference, gotchas
- [docs/ADDING-A-STACK.md](docs/ADDING-A-STACK.md) — new stack profiles
- [docs/LIFT-LOG.md](docs/LIFT-LOG.md) — harvesting learnings back
- [firestarter.config.json](firestarter.config.json) — the variable manifest
