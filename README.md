<h1 align="center">🔥 Project Firestarter</h1>

<p align="center">
  <strong>Start every new project already wired for production.</strong><br>
  A version-controlled template that bakes in the best practices, gotchas, and
  CI/CD a project usually earns the hard way — so day one looks like month three.
</p>

<p align="center">
  <a href="https://github.com/pulkitsinghal/project-firestarter/actions/workflows/ci.yml"><img src="https://github.com/pulkitsinghal/project-firestarter/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/stacks-2-blue" alt="stacks">
  <img src="https://img.shields.io/badge/host%20SDKs-0-success" alt="no host SDKs">
  <img src="https://img.shields.io/badge/PRs-AI%20reviewed%20%26%20auto--merged-purple" alt="AI reviewed">
</p>

<p align="center"><a href="https://pulkitsinghal.github.io/project-firestarter/"><strong>📄 Read the landing page →</strong></a></p>

---

## Why it exists

Every new repo re-pays the same tax: wire up CI, write the commit conventions,
remember the Docker gotchas, set up review and auto-merge, document the
onboarding. It takes days, it's inconsistent across projects, and the hard-won
lessons from the *last* project rarely make it into the next one.

Firestarter pays that tax **once**. It distills the shared developer- and
devops-level scaffolding from real sibling projects into one cookiecutter-style
template, so a new repo starts with all of it already in place — and a documented
process ([LIFT-LOG](docs/LIFT-LOG.md)) for folding new lessons back in.

## The merits

| Merit | What it means for you |
|-------|----------------------|
| 🐳 **Zero host SDKs** | Everything runs in Docker. No "install Node/Python/Dart" — `make up` and go. New contributors are productive in one command. |
| 🤖 **AI-reviewed, auto-merging PRs** | A workflow calls the Anthropic API, posts a verdict, and `auto-merge` squash-merges green PRs. No human-review bottleneck. |
| ✅ **Green-before-push** | One `make precommit` mirrors every CI gate locally, in Docker. Stop pushing to "see if CI passes." |
| 📐 **Conventions enforced, not hoped-for** | Conventional Commits + forward-only migrations enforced by git hooks *and* CI. |
| 🔭 **It documents itself** | A storyboard harness renders a live *planned-vs-implemented* map with screenshots straight from the running app. |
| 🚀 **Share in one button** | `make deploy` exposes your local app on a public Cloudflare URL — no account, no cloud bill. |
| 🧩 **Two real stacks + opt-in add-ons** | FastAPI+Next.js or Supabase+Flutter, with the painful gotchas baked into comments. k8s is one flag away when you need it. |
| 🤝 **AI-agent ready** | A root `AGENTS.md` (the cross-tool standard) lets Claude Code, Codex, Cursor, or Aider drive the repo on sight. |

## Proven, not theoretical

Firestarter **runs its own template on itself.** It has the same CI, AI review,
and auto-merge it ships — and every feature in it landed through that pipeline:
4 PRs opened, reviewed, and auto-merged green. The dog food is the dinner.

## Quickstart

You need only Docker — no host language toolchains.

```bash
# Interactive — prompts for every value (Enter accepts the default):
./bin/firestart.sh

# Non-interactive:
./bin/firestart.sh --defaults --set project_slug=lighthouse --set stack=fastapi-next

# Optional add-on (off by default):
./bin/firestart.sh --set include_k8s=yes
```

It stamps a new project to `../<github_repo>`, then prints the next steps:

```bash
cd ../project-lighthouse
git init && git add -A && git commit -m "chore: scaffold from firestarter"
make hook-install            # activate the opt-in git hooks
make up && make migrate      # boot the stack
gh secret set ANTHROPIC_API_KEY   # turn on the AI reviewer
```

## What's in the box

- **Universal meta-layer** (`template/`) — `AGENTS.md`, `CLAUDE.md`,
  `ARCHITECTURE.md`, `CONTRIBUTING.md`, opt-in git hooks, PR/issue templates,
  `SECURITY.md`, and the full CI suite: **AI PR review · auto-merge · commit-lint
  · storyboard**.
- **Stack profiles** (`stacks/`):
  - `fastapi-next` — FastAPI + PostgreSQL/pgvector + Redis · Next.js.
  - `supabase-flutter` — Postgres/PostGIS + PostgREST + GoTrue · Flutter · React.
- **Optional add-ons** (`addons/`) — e.g. `k8s` Kustomize (opt in with
  `include_k8s=yes`).

How it works under the hood: a `firestarter.config.json` manifest declares the
variables; a stdlib-only generator (run **in Docker**, no pip) substitutes
`{{ tokens }}` and overlays the chosen stack. Token substitution is
whitelist-only, so GitHub Actions `${{ … }}` is never clobbered.

## Learn more

- 🗺️ [docs/ANATOMY.md](docs/ANATOMY.md) — file-by-file map: what each piece is, why it exists, and which sibling it came from
- ➕ [docs/ADDING-A-STACK.md](docs/ADDING-A-STACK.md) — author a new stack profile
- ♻️ [docs/LIFT-LOG.md](docs/LIFT-LOG.md) — how learnings get harvested back into the template
- 🤖 [AGENTS.md](AGENTS.md) — operating brief for any AI session
