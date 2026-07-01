# Lift Log — harvesting learnings back into the template

This template is a living distillation, not a one-time snapshot. When a sibling
project discovers something worth standardizing, lift it back here so the *next*
project starts with it.

## When to lift

Lift something when it's **process or infrastructure that every sibling would
want**, not project-specific behaviour. Good candidates:

- A CI workflow fix (a race, a permissions bug, a better cache key).
- A new git hook or a hardening of an existing one.
- A documented gotcha (an image pin, a startup-ordering quirk, an SDK flag).
- A better `make` target or a clearer doc section.

Do **not** lift: domain logic, product copy, anything tied to one project's
schema or features.

## How to lift

1. Generalize it: replace project-specific names with `{{ tokens }}`.
2. Decide where it belongs:
   - Universal? → `template/`.
   - Stack-specific? → the relevant `stacks/<stack>/`.
3. If it's a gotcha, bake it as an **inline comment** next to the code it guards,
   and add a row to `docs/ANATOMY.md`.
4. Add an entry to the log below.
5. Re-stamp a throwaway project (`./bin/firestart.sh --defaults --output /tmp/smoke`)
   and confirm it still generates cleanly.

## Periodic sweep

Every so often (e.g. when starting a new project), skim the siblings'
`PROJECT_STATUS_AND_NEXT_STEPS.md`, recent CI changes, and any new
`docs/postmortems/` for things worth lifting.

## Log

| Date | Lifted | From | Into |
|------|--------|------|------|
| 2026-06-29 | Initial distillation: meta-layer + two stack profiles | pilgrim + healer | template/ + stacks/ |
| 2026-06-29 | Self-CI: firestarter runs its own ci/review/auto-merge + lenient branch protection | (best-practice) | .github/workflows/ |
| 2026-06-29 | Sibling glean: dependabot, PR + issue templates, local ai-review.sh, postmortem template, .editorconfig, SECURITY.md, one-button Cloudflare deploy | pilgrim | template/ + stacks/ |
| 2026-06-29 | Storyboard manifest harness: planned-vs-implemented map rendered to docs/STORYBOARD.md with committed previews (#9) | pilgrim | stacks/*/storyboard/ |
| 2026-06-29 | Optional add-on mechanism + k8s Kustomize scaffold (include_k8s, default off) (#10) | pilgrim | addons/k8s/ + bin/generate.py |
| 2026-06-29 | gitleaks secret-scan workflow (required by auto-merge) + make target — free push-protection for private repos | security audit | template/ + stacks/ |
| 2026-06-29 | Elevated storyboarding from a merit to a stated **precept** (hard rule #6 + template AGENTS precept/invariant) | (best-practice) | AGENTS.md + template/AGENTS.md |
| 2026-06-30 | Deny-by-default RPC EXECUTE in `001_init.sql`: revoke the implicit `PUBLIC`/`anon` grant so PostgREST doesn't expose future functions until opted in (from a verified anon-RPC exploit) | pilgrim | stacks/supabase-flutter/ |
| 2026-06-30 | SemVer + version-sync: canonical `/VERSION`, Keep-a-Changelog seed, per-stack `scripts/sync_version.sh` + `make version-sync` (coreutils, no SDK) | healer | template/ + stacks/ |
| 2026-06-30 | Migration-rollback runbook (genericized): revert-as-forward-migration + emergency surgery; AGENTS pointer + OPEN_QUESTIONS backup stub | pilgrim | template/docs/ |
| 2026-06-30 | Flutter app now tested in CI: widget smoke test + `flutter test` wired into the Tests job and `make test`/`precommit` (was analyze-only) | pilgrim | stacks/supabase-flutter/ |
| 2026-06-30 | Dispatchable `deploy.yml` (universal): self-hosted `workflow_dispatch` → `make up` + `make deploy` (Cloudflare quick-tunnel, no secrets) | pilgrim | template/.github/workflows/ |
| 2026-06-30 | CI cost: `concurrency: cancel-in-progress` on every workflow except auto-merge (unsafe to cancel a merge); required checks keep running on every PR (no risky path-filters) | pilgrim | template/ + stacks/ |
| 2026-06-30 | Go-Live runbook (genericized): clean-slate run/verify + a pre-launch checklist wiring secrets, release, deploy, and backups together | healer | template/docs/ |
| 2026-06-30 | Compliance-posture template (generalized from HIPAA_POSTURE): in/out-of-scope stance + risk→control→where table | healer | template/docs/ |
| 2026-06-30 | RPC catalog convention (seed + entry template): documents PostgREST RPC grants + signatures; reinforces the deny-by-default posture | pilgrim | stacks/supabase-flutter/docs/ |
| 2026-06-30 | SECURITY.md: "no default/guessable secret in deploy configs" rule (fail-closed, read from env) — from pilgrim's demo-JWT deploy bug | pilgrim | template/ |
| 2026-06-30 | `include_auth` add-on (fastapi-next): passwordless OTP core (models/store/flows/delivery/router/main + smoke test), in-memory & dependency-free; OAuth flow, durable store, frontend widget deferred | healer | addons/auth/ + bin/generate.py |
| 2026-06-30 | `include_bug_report` add-on (supabase-flutter): in-app capture → `report_bug` RPC (deny-by-default) → SQL-formatted `pull-bug-reports.sh` → GitHub issue. dep-free `dart:io` client (pilgrim's riverpod/supabase sheet adapted to the skeleton) | pilgrim | addons/bug_report/ + bin/generate.py |
| 2026-06-30 | Remote-agent-access hardened spec (doc-only, no executable): trigger-don't-connect via self-hosted `deploy.yml`, never expose `docker.sock`; broker requirements + threat model. Deliberately not a stamped default | pilgrim (security pass) | template/docs/ |
| 2026-06-30 | auth follow-up: durable `PostgresAuthStore` (`002_auth.sql` + `AUTH_STORE=postgres`), psycopg3 async, no new dep; skip-if-no-DB integration test drives the OTP flow through it | healer | addons/auth/ |
| 2026-06-30 | bug_report follow-up: dependency-free screenshot capture (`ScreenshotBoundary` = keyed `RepaintBoundary` → base64 PNG), thumbnail + attach toggle; widget test captures for real | pilgrim | addons/bug_report/ |
| 2026-06-30 | auth follow-up: Next.js OTP sign-in widget (`auth-widget.tsx`) + `layout.tsx`/`next.config.mjs` overlays (adds `/auth/*` proxy rewrite); verified with strict tsc + next build | healer | addons/auth/ |
| 2026-06-30 | GoTrue local bootstrap: `backend/initdb/00_create_auth_schema.sql` (CREATE SCHEMA auth + `public.schema_migrations` seed) so GoTrue doesn't crash-loop on a fresh volume; single-migration-path warning; `GOTRUE_*_AUTOCONFIRM` for local OTP | pilgrim | stacks/supabase-flutter/ |
| 2026-06-30 | Hermetic/integration test split (fastapi-next): `make backend-itest` + `integration` pytest marker + `tests/integration/` gated on `TEST_DATABASE_URL` (default `backend-test` stays offline); CI passes the URL so the seed runs | healer | stacks/fastapi-next/ |
| 2026-06-30 | `include_ssrf_fetch` add-on (fastapi-next): dependency-free SSRF-guarded URL fetch (scheme + public-IP-only + redirect re-validation + size/time bounds + stdlib HTML→text), offline tests | healer | addons/ssrf_fetch/ + bin/generate.py |
| 2026-06-30 | Least-privilege `permissions: contents: read` on every read-only workflow (commit-lint, secret-scan, storyboard, both ci.yml, splash-ci) — caps `GITHUB_TOKEN` blast radius; write workflows (ai-pr-review/auto-merge/deploy) keep their scopes | pilgrim | template/ + stacks/ |
| 2026-06-30 | Host-requirements onboarding runbook (genericized): host tools (Docker/git/make/gh) + "do NOT install on host" table + opt-in iOS/Android; README pointer | pilgrim | template/docs/ |
| 2026-07-01 | Splash Vite/webpack file-watch polling (`CHOKIDAR_USEPOLLING`/`WATCHPACK_POLLING`) as a baked gotcha — HMR fires over a Docker bind mount on macOS/Windows/WSL2 when you run a dev server (inert for the default `pnpm build`). Skipped the pnpm-store volume: cross-volume with the existing `splash_node_modules` mount, pnpm can't hardlink → net loss | pilgrim | stacks/supabase-flutter/ |
| 2026-07-01 | Self-audit: `GOTRUE_JWT_SECRET` was a hardcoded default (violated the #25 no-baked-secret rule) → env-driven `${JWT_SECRET:-<dev-only>}` with override/PGRST-must-match comment | security audit (#25) | stacks/supabase-flutter/ |
| 2026-07-01 | Third stack profile: `chrome-extension` (MV3 + esbuild + Vitest + host-only Playwright e2e + storyboard). First **DB-less** stack — adapts the DB-centric meta-layer (no postgres/migrate; overrides storyboard.yml). Verified: build/typecheck/vitest + e2e tsc + storyboard screenshot all pass | auggie-chrome-extension | stacks/chrome-extension/ + firestarter.config.json |
