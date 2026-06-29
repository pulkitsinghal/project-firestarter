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
