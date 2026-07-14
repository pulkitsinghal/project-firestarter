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
devops-level scaffolding from a family of sibling projects so a new repo starts
with the best practices already wired in.
Read [README.md](README.md) and [docs/ANATOMY.md](docs/ANATOMY.md) first — ANATOMY
is the file-by-file map of what everything is and where it came from.

## The two jobs you'll be asked to do

### 1. Stamp a new project
```bash
./bin/firestart.sh                                   # interactive
./bin/firestart.sh --values examples/fastapi-next.answers.json --output ../project-x
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
3. **Every declared stack must keep stamping cleanly.** After any change, re-run
   the verification below for every example answer file.
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
7. **One workstation CA for local HTTPS.** Keep the cross-agent policy in
   `template/docs/LOCAL_TLS.md`: generated projects reuse the owner-manifested
   canonical proxy/CA, never create per-project roots, never expose CA keys, and
   never persist certificate-verification bypasses.
8. **Feature handoffs are evidence bundles.** When handing completed work to a
   user or developer, follow `template/docs/FEATURE_HANDOFF.md`. Always record
   the acceptance path, a meaningful failure/retry/rollback/cleanup path, exact
   automated and live checks, and inspectable evidence. Visible UI work also
   needs real rebuilt-app storyboard frames and a compact state/flow map. For a
   material multi-step UI flow, add a short captioned release cut only when the
   repository already provides a reproducible Dockerized harness and named Make
   target; otherwise mark video N/A and give a still-frame walkthrough. Natural
   voice narration is optional, never a universal completion gate.
   Non-visual work substitutes request/response, log, migration, build/output,
   or state-transition evidence. Handoff artifacts use synthetic/test data and
   never contain credentials, secrets, private records, or production data.
   For Firestarter itself, exercise the relevant stamped project output; the
   generated-project commands in the playbook are not root-level commands.

## Verify before you commit

Run the generator in Docker for every stack example and check nothing leaked:

```bash
SB=$(mktemp -d)
for values in examples/*.answers.json; do
  ex="${values##*/}"
  ex="${ex%.answers.json}"
  docker run --rm -v "$PWD:/gen:ro" -v "$SB:/out" -w /gen python:3.12-slim \
    python /gen/bin/generate.py --values "/gen/$values" --output "/out/$ex"
done
# No unsubstituted tokens (JSX style={{ }} is the only allowed match):
grep -rn '{{' "$SB" | grep -vE '\$\{\{|style=\{\{' || echo "✓ no leaks"
# GitHub expressions preserved:
grep -c '\${{' "$SB/fastapi-next/.github/workflows/auto-merge.yml"
```

Then sanity-check generated shell (`bash -n .../migrate.sh`), and that
`bin/generate.py` compiles (`python -m py_compile`).

## Commit & PR conventions (this repo)

- **Conventional Commits**: `type(scope): subject` (≤100 chars). Scopes:
  `template stacks bin docs ci build`.
- Branch off `master`; open a PR; squash-merge. Don't push straight to `master`.
- **Parallel sessions → use a git worktree (disk permitting).** If more than one
  session/agent may touch this repo at once, give each its own worktree on its
  own branch instead of sharing one checkout — isolated working tree + index per
  session avoids clobbering each other's uncommitted changes or branch switches
  (`git worktree add ../firestarter-<slug> -b <branch> origin/master`;
  `git worktree remove` when done). The `.git` is shared, so it costs ~one extra
  checkout — worth it when you have the disk space, skip it when you don't.
- This repo runs the same CI it ships: `ci.yml` (Tests + Lint & Typecheck),
  `commit-lint.yml`, `ai-pr-review.yml`, `auto-merge.yml`. Label a PR
  `auto-merge` and it squash-merges once checks are green and the AI verdict
  isn't BLOCKING. Real reviews need the `ANTHROPIC_API_KEY` secret; without it
  the reviewer degrades to a NON-BLOCKING stub.
- `master` has **lenient branch protection** (free-tier friendly): required
  checks `Tests` / `Lint & Typecheck` / `Conventional Commits`, **0 required
  approvals** (no human reviewer — the AI review + auto-merge gate instead),
  admins exempt, no strict/up-to-date requirement.

### Completion loop

For Firestarter changes, “done” means: isolated feature branch/worktree when
parallel work is possible → every declared stack stamps cleanly → explicit-path
staging and full-diff self-review → conventional commit → pushed PR → code
review + green CI → squash merge → fast-forward local `master` → rerun the
generator/smoke gate from merged `master` → deploy generated-project changes
only under their `docs/DEPLOY_POLICY.md` and verify live → rollback/revert on a
failed live check → delete the merged branch/worktree and record the evidence.
This defines the end state but does not grant missing commit, merge, credential,
production, or user-test authority; stop and hand off at the relevant boundary.
Never skip directly from implementation to a success claim.

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
- [template/docs/FEATURE_HANDOFF.md](template/docs/FEATURE_HANDOFF.md) — the
  evidence bundle required when a feature goes to user/dev review
- [template/docs/LOCAL_TLS.md](template/docs/LOCAL_TLS.md) — shared local-CA policy
- [firestarter.config.json](firestarter.config.json) — the variable manifest
