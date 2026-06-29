# Changelog

All notable changes to the firestarter template. See
[docs/LIFT-LOG.md](docs/LIFT-LOG.md) for the harvesting process.

## [0.1.0] — 2026-06-29

### Added
- Cookiecutter-style generator (`bin/generate.py`) run in Docker via
  `bin/firestart.sh` — no host SDKs. Whitelist token substitution so GitHub
  Actions `${{ }}` expressions are never clobbered.
- `firestarter.config.json` variable manifest.
- **Universal meta-layer** (`template/`): `AGENTS.md`, `CLAUDE.md`,
  `ARCHITECTURE.md`, `CONTRIBUTING.md`, `PROJECT_STATUS_AND_NEXT_STEPS.md`,
  `README.md`, opt-in git hooks, `.gitmessage`, `.gitignore`, and the CI suite
  (ai-pr-review, auto-merge, commit-lint, storyboard) plus `docs/`.
- **Stack profile `fastapi-next`** (project-healer lineage): compose, Makefile,
  CI, FastAPI backend + migrations + tests, Next.js frontend, Playwright
  storyboard.
- **Stack profile `supabase-flutter`** (project-pilgrim lineage): Supabase-style
  compose with ARM64/PostgREST/GoTrue gotchas, Makefile, CI + splash-ci, PostGIS
  migration, Flutter app, Dart service layer, Vite/React splash, storyboard.
- Docs: `ANATOMY.md` (file-by-file map), `ADDING-A-STACK.md`, `LIFT-LOG.md`.
- **Self-CI**: firestarter runs the same ci / ai-pr-review / auto-merge it ships,
  with lenient (free-tier-friendly) branch protection.
- **Sibling-gleaned tooling** in the template: PR + issue templates, a local
  `scripts/ai-review.sh`, blameless postmortem template, `.editorconfig`,
  `SECURITY.md`, per-stack `dependabot.yml`, and a one-button Cloudflare-tunnel
  `make deploy`.
- **Storyboard upgraded** to a manifest-driven planned-vs-implemented map
  (`storyboard/manifest.json` → committed `docs/STORYBOARD.md`) with hard content
  assertions as a regression guard.
- **Optional add-ons** (`addons/`) via `include_<name>` flags — first one: `k8s`
  (Kustomize base + staging/production overlays per stack, `include_k8s=yes`).
- **Secret scanning**: gitleaks-in-Docker (`Secret Scan`, pinned `v8.30.1`),
  required by auto-merge, with a `.gitleaks.toml` — free push-protection
  equivalent for private repos without paid GitHub Secret Protection.
- Marketing: a GitHub Pages landing page (`docs/index.html`) and a
  merit-forward README.
