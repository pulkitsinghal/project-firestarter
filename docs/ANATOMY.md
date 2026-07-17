# Anatomy — what every piece is and where it came from

This is the componentization map. The template is split into a **universal
meta-layer** (identical for every project) and **stack profiles** (the parts
that differ by tech stack). The generator overlays the chosen stack on top of
the meta-layer.

## Repo layout

```
firestarter.config.json   variable manifest (the "cookiecutter.json")
bin/
  firestart.sh            Dockerized entrypoint (no host SDK)
  generate.py             the generator (stdlib only)
template/                 UNIVERSAL meta-layer — copied for every project
stacks/
  fastapi-next/           FastAPI + Next.js (fastapi-next lineage)
  supabase-flutter/       Supabase + Flutter + React (supabase-flutter lineage)
  chrome-extension/       Manifest V3 + TypeScript (browser-extension lineage)
addons/                   OPTIONAL modules, overlaid only when opted in
  k8s/<stack>/            Kustomize manifests (include_k8s=yes)
docs/                     this map, plus how-to guides
```

## The universal meta-layer (`template/`)

| File | What it is | Lifted from |
|------|-----------|-------------|
| `AGENTS.md` | Standing brief for AI agents: branch/commit/merge workflow, push policy, gates | both (sibling phrasing) |
| `CLAUDE.md` | Claude Code context: owner preferences, invariants, CI table | both |
| `CONTRIBUTING.md` | Human-facing short version of the workflow | both |
| `ARCHITECTURE.md` | Scaffold for layers/data-model/invariants | both (genericized) |
| `PROJECT_STATUS_AND_NEXT_STEPS.md` | Living "where are we" doc | both |
| `README.md` | Project front page with quickstart | both |
| `VERSION` | Canonical SemVer string; `make version-sync` propagates it into the stack's package manifests | sibling |
| `CHANGELOG.md` | Keep-a-Changelog seed (`[Unreleased]` + `[0.1.0]`), tied to `/VERSION` | sibling |
| `.gitmessage` | Conventional-commit template (`git config commit.template`) | both |
| `.gitignore` | Covers Python, Node, Dart/Flutter, Docker, storyboard output | union of both |
| `.githooks/commit-msg` | Enforces conventional-commit subject (mirrors CI) | both |
| `.githooks/pre-commit` | Runs `make precommit` when source changes | both |
| `.githooks/pre-push` | Non-blocking "you're N commits ahead" reminder | both |
| `.githooks/README.md` | Why hooks are opt-in + how to enable | both |
| `.github/workflows/ai-pr-review.yml` | **Crown jewel** — calls the Anthropic API directly, posts a BLOCKING/NON-BLOCKING/LGTM verdict, breaks BLOCKING loops after 3 cycles | both |
| `.github/workflows/auto-merge.yml` | Squash-merges `auto-merge`-labelled PRs when checks are green and the verdict isn't BLOCKING | both |
| `.github/workflows/auto-merge-label.yml` | **Opt-OUT** companion: auto-applies the `auto-merge` label to every non-draft PR on open (idempotently ensures `auto-merge`/`hold` labels). Hold a PR back with a draft or the `hold` label. Removes the "someone forgot the label" failure mode | sibling |
| `.github/workflows/commit-lint.yml` | Validates every commit subject in a PR | both |
| `.github/workflows/storyboard.yml` | Boots the stack, runs Playwright, uploads screenshots (non-blocking) | both (sibling origin) |
| `.github/workflows/secret-scan.yml` | gitleaks-in-Docker secret scan (pinned `v8.30.1`); **required** by auto-merge. Free push-protection equivalent for private repos without paid GitHub Secret Protection | best-practice |
| `.github/workflows/deploy.yml` | `workflow_dispatch` one-button beta deploy default for server-backed profiles: `make up` + `make deploy` on a self-hosted runner (Cloudflare quick-tunnel, no secrets). Client-only profiles must replace this with their distribution path before go-live | sibling |
| `.gitleaks.toml` | gitleaks config: extends default rules + allowlists build-artifact dirs (so local `make secret-scan` on a dirty tree is clean). Add narrow allowlists for known public/test fixtures | best-practice |
| `docs/ci-secrets.md` | How to set `ANTHROPIC_API_KEY` without leaking it | sibling |
| `docs/HOST_REQUIREMENTS.md` | Onboarding: the few tools that live on the host (Docker/git/make/gh) + a "do NOT install on host" table + opt-in native-mobile sections | sibling |
| `docs/LOCAL_TLS.md` | Shared local-CA policy and macOS/Caddy runbook: fingerprint-checked trust, one canonical issuer, no agent-held CA keys, verified rollout/rollback | local-ai certificate incident |
| `docs/OPEN_QUESTIONS.md` | Template for the deferred-decisions log (incl. a backup-strategy stub) | both |
| `docs/GO_LIVE.md` | Clean-slate run/verify/go-live checklist tying together secrets, release, deploy, backups | sibling |
| `docs/DEPLOY_POLICY.md` | The *decision frame* `GO_LIVE`/`DEPLOY` don't cover: when a deploy is **self-authorized** (3 conditions — ample testing, snapshot verification, post-deploy check) vs. what stays owner-only (credentials, prod-DB migrations, billing) | sibling |
| `docs/COMPLIANCE_POSTURE.md` | Fill-in template: which regimes you're in/out of scope for + a risk→control→where table | sibling |
| `docs/REMOTE_AGENT_ACCESS.md` | Hardened decision doc for remote-driving the local stack: trigger-don't-connect (self-hosted `deploy.yml`), never expose `docker.sock`. No executable shipped | sibling (security-reviewed) |
| `docs/migration-rollback.md` | Runbook for undoing a migration the forward-only way (revert migration + emergency surgery) | sibling |
| `docs/storyboard-harness.md` | What the storyboard/manifest harness is and how to extend it | both |
| `docs/STORYBOARD.md` | Seed for the auto-generated planned-vs-implemented map (regenerated by `make storyboard`) | sibling |
| `docs/FEATURE_HANDOFF.md` | Evidence-bundle precept: exact acceptance/failure/recovery/verification; real storyboard frames and state map for visible work; conditional release cut only with a reproducible harness; non-visual substitution rule | reusable sibling release workflow |
| `docs/postmortems/TEMPLATE.md` | Blameless postmortem template | sibling |
| `.github/pull_request_template.md` | Summary / Why / impact / test plan / evidence-backed handoff + checklist | sibling |
| `.github/ISSUE_TEMPLATE/{bug,feature,safety-concern,config}.yml` | Issue forms incl. a generic safety/privacy form | sibling |
| `scripts/ai-review.sh` | Local pre-PR review helper (diff + reviewer prompt to pipe into a chat) | sibling |
| `.editorconfig` | Cross-editor whitespace/indent consistency | best-practice |
| `SECURITY.md` | Private vuln-disclosure policy + secret-handling rules | best-practice |
| `.gitattributes` | Pins `*.sh` + `.githooks/*` to LF so host-run hooks/scripts survive a Windows checkout (no `bad interpreter: /bin/bash^M`) | sibling |
| `.claude/settings.json` + `.claude/hooks/session-start-clean-tree.sh` (+ `README.md`) | Session-isolation guardrails: deny-rules for the blanket staging forms + a warn-only, fail-open SessionStart dirty-tree hook (Claude Code; other tools get the same norm from `AGENTS.md`) | sibling |
| `.env.example` | Env-var manifest for `make verify-env` — value `__REPLACE_ME__` (or a `# required` tag) marks a var required; committed (un-ignored) | a sibling project |
| `scripts/smoke.sh` | Syntax-checks the project's own shipped shell/hooks/python (`bash -n`/`sh -n`/`py_compile`; python3 optional, no host SDK). Wired into each stack's Tests job + `make smoke`/`precommit` | a sibling project |
| `scripts/verify-env.sh` | Preflight that fails fast when a required env var is unset or still a placeholder; hardened line-by-line loader | a sibling project |

### Why these are universal
They encode *process*, not *stack*: conventional commits, forward-only
migrations, AI-reviewed auto-merge, no host SDKs, opt-in hooks. Every sibling
project wants all of it regardless of language.

## Stack profile: `fastapi-next` (fastapi-next lineage)

| File | Purpose |
|------|---------|
| `docker-compose.yml` | postgres (pgvector) + redis + backend + frontend; `tools`/`node`/`storyboard` profiles |
| `Makefile` | `up/down/migrate/test/lint/precommit/storyboard/hook-install` — all via Docker |
| `scripts/sync_version.sh` + `make version-sync` | Propagate `/VERSION` into `backend/pyproject.toml` + `frontend/package.json` (host coreutils, no SDK) |
| `.github/workflows/ci.yml` | Jobs **Tests**, **Lint & Typecheck**, **Build** (names matched by auto-merge) |
| `backend/` | FastAPI app, `pyproject.toml` (ruff/mypy/pytest), `001_init.sql`, `scripts/migrate.sh`, a smoke test, and a hermetic-vs-integration test split (`make backend-itest` + `integration` marker + `tests/integration/` gated on `TEST_DATABASE_URL`) |
| `frontend/` | Next.js App Router skeleton with an `/api` proxy to the backend; exact patched dependencies are locked and installed with `npm ci` |
| `storyboard/` | Playwright runner pinned to `mcr.microsoft.com/playwright` |
| `.github/dependabot.yml` | Grouped weekly updates (pip + npm + github-actions), `chore:`/`ci:` prefixes |
| `DEPLOY.md` + `cloudflared` deploy profile | One-button Cloudflare quick-tunnel to expose the frontend publicly (no account) |
| `storyboard/manifest.json` + render | Manifest-driven planned-vs-implemented map → committed `docs/STORYBOARD.md` |

## Stack profile: `supabase-flutter` (supabase-flutter lineage)

| File | Purpose |
|------|---------|
| `docker-compose.yml` | postgis (ARM64-safe `imresamu/postgis`) + redis + postgrest + gotrue; `dart`/`flutter`/`splash`/`storyboard` profiles, with the key gotchas inline |
| `Makefile` | Adds `flutter-analyze`, `flutter-format-check`, `dart-test`, `splash-build`, `pgrst-reload` |
| `scripts/sync_version.sh` + `make version-sync` | Propagate `/VERSION` into both `pubspec.yaml` + `splash/package.json` (host coreutils, no SDK) |
| `scripts/rotate-secrets.sh` + `make rotate-secrets` | Mint a fresh `JWT_SECRET`/`DB_PASSWORD` + matching `anon`/`service_role` JWTs off the dev-only compose default → gitignored `.env.deploy` (chmod 600); JWTs minted in a throwaway `node:20-alpine` (no host SDK). Makes the "no default/guessable secret" rule actionable — rotate before exposing the stack. Apply with `docker compose --env-file .env.deploy up` |

| `.github/workflows/ci.yml` | Jobs **Tests** (Dart) + **Lint & Typecheck** (flutter analyze + format) |
| `.github/workflows/anon-execute-guard.yml` | Path-gated guard: applies migrations to a throwaway stack, fails if a function is `anon`-executable but not in `backend/security/anon_execute_allowlist.txt` (continuous backstop to `001_init`'s deny-by-default) |
| `.github/workflows/rls-guard.yml` | Path-gated guard (table-level sibling of the anon-execute guard): applies migrations to a throwaway stack, fails if a public app table has Row-Level Security off but isn't in `backend/security/rls_disabled_allowlist.txt` (Supabase advisor `rls_disabled_in_public`) |
| `.github/workflows/splash-ci.yml` | Path-gated **Build** for the splash page (Docker, no host Node) |
| `backend/` | PostGIS `001_init.sql` (+ `anon` role/grant pattern), `scripts/migrate.sh` |
| `app/` | Flutter skeleton + a widget smoke test (`app/test/smoke_test.dart`) so `flutter test` runs in the **Tests** job |
| `services/` | Dart service-layer package + smoke test (the domain source of truth) |
| `docs/rpc-catalog.md` | Contract for PostgREST RPCs (grants + signatures); seeds the deny-by-default convention with an entry template |
| `backend/security/` | Two continuous guards over the anon surface: `check_anon_execute.sh` + `anon_execute_allowlist.txt` (function EXECUTE) and `check_rls_enabled.sh` + `rls_disabled_allowlist.txt` (table RLS) — the reviewed anon surfaces the guard workflows enforce |
| `splash/` | Minimal Vite + React + TS landing page that actually builds |
| `storyboard/` | Playwright runner + manifest renderer pointed at the splash service |
| `.github/dependabot.yml` | Grouped weekly updates (pub + npm + github-actions), `chore:`/`ci:` prefixes |
| `DEPLOY.md` + `cloudflared` deploy profile | One-button Cloudflare quick-tunnel (defaults to the PostgREST API) |
| `storyboard/manifest.json` + render | Manifest-driven planned-vs-implemented map → committed `docs/STORYBOARD.md` |

### Documented gotchas baked into this stack
- **ARM64 PostGIS:** `imresamu/postgis:15-3.4`, not `postgis/postgis` (amd64-only).
- **PostgREST schema cache:** restart `postgrest` after every migration (`make pgrst-reload`).
- **GoTrue `search_path=auth`:** so its queries resolve to `auth.users`; pin the version. On a **fresh volume** the `auth` schema must exist first — `backend/initdb/00_create_auth_schema.sql` (mounted as `docker-entrypoint-initdb.d`) creates it (+ a `public.schema_migrations` seed GoTrue v2.191.0 needs), or GoTrue crash-loops on first boot. `GOTRUE_*_AUTOCONFIRM` let local OTP signup complete with no SMTP/SMS.
- **Single migration path:** never mount `./backend/migrations` as `initdb.d` — it bypasses `{{ migrations_table }}` and double-applies; `make migrate` is the only path.
- **Flutter format-check is read-only:** exits 1 but doesn't write; a separate target applies.
- **PostgREST RPC exposure:** Postgres grants `EXECUTE` to `PUBLIC` by default and PostgREST serves any function `anon`/PUBLIC can execute at `POST /rpc/<name>`, so `REVOKE … FROM anon` alone is a no-op. `001_init.sql` strips the implicit `PUBLIC` grant (deny-by-default); expose an RPC by granting `EXECUTE` to `anon` explicitly.
- **Public-table exposure (RLS):** the table-level sibling of the RPC gotcha (Supabase advisor `rls_disabled_in_public`). PostgREST/Supabase Cloud grant anon blanket access to public tables by default, so a public table is world-readable until Row-Level Security is on — a `GRANT SELECT … TO anon` then exposes *every* row, not just the intended ones. `001_init.sql` enables RLS on `locations` + a permissive `USING (is_approved)` SELECT policy, and `migrate.sh` enables deny-all RLS on the `{{ migrations_table }}` bookkeeping table; `check_rls_enabled.sh` (CI `rls-guard.yml`) ratchets it — a new RLS-off table fails unless allow-listed.

## Stack profile: `chrome-extension` (chrome-extension lineage)

A **DB-less** stack — a Manifest V3 browser extension is pure client code, so
there's no `postgres`, no `backend/`, and `make migrate` is a no-op. The
meta-layer's DB-flavored docs (e.g. `migration-rollback.md`) still stamp but are
inert for this stack.

| File | Purpose |
|------|---------|
| `docker-compose.yml` | `node-tools` (node:22-slim) build/test/typecheck; `storyboard` profile. No DB. |
| `Makefile` | `install/build/typecheck/test-unit/test/lint/precommit/clean/storyboard/e2e/hook-install`; `up` builds + prints load-unpacked instructions, `down` cleans, `migrate` is a documented no-op |
| `.github/workflows/ci.yml` | Jobs **Tests** (vitest), **Lint & Typecheck** (`tsc --noEmit`), **Build** (esbuild) — the contract names |
| `.github/workflows/storyboard.yml` | Overrides the meta-layer's DB-centric one: builds the extension, then runs the harness (no postgres/migrate) |
| `extension/` | MV3 skeleton: `public/manifest.json` (side panel + background SW + content script), `src/` (background/content-script/sidebar + a pure-logic module & Vitest test), `scripts/build.mjs` (esbuild → IIFE bundles + static copy), `tsconfig`, `vitest.config` |
| `e2e/` | Playwright MV3 harness: a fixture that `--load-extension`s a persistent Chromium (with container-safe `--no-sandbox`/`--disable-dev-shm-usage` flags) and resolves the extension id from the background service-worker URL + a side-panel smoke spec. `e2e/scripts/with-xvfb.sh` runs it headed on a display-less runner (idempotent Xvfb boot) |
| `.github/workflows/e2e.yml` | **Opt-in** (`workflow_dispatch`) headed e2e on a display-less runner via Xvfb — least-privilege, a distinct job name, never a required gate. Closes the "wire an opt-in job once you have a runner with a display" TODO |
| `storyboard/` | Screenshots the built side panel (`dist/sidebar.html`) → committed `docs/STORYBOARD.md` (honours the storyboard precept for a UI with no server) |
| `tools/demo-recording/` | Records the **real** side panel as video (page + panel + cursor) with no login: iframe the live `sidebar.html` into a staged page, seed auth/data offline via the service worker, capture with Playwright `recordVideo`. A fill-in-the-blanks `record.template.mjs` + generic primitives (`visual_cursor_overlay.js`, `video_processor.py`) + a README of the hard-won gotchas. Complements `storyboard/` (stills) with a moving release/QA clip |

### Documented gotchas baked into this stack
- **esbuild doesn't type-check:** `tsc --noEmit` is a separate gate (the "Lint & Typecheck" job).
- **Per-page video misses the side panel:** to record the panel + cursor, iframe the live `sidebar.html` into one page and use Playwright `recordVideo` (not `ffmpeg x11grab`, which is black on a bare Xvfb). See `tools/demo-recording/README.md`.
- **No host SDKs, arm64 native deps:** node_modules lives in a named volume so the container builds esbuild's platform-specific binary, not the host's.
- **e2e is host-only:** loading an MV3 extension needs a real headed Chromium — a headless container can't, so it isn't a CI gate.

## Optional add-ons (`addons/`)

Add-ons are opinionated or heavy modules kept **out of the default scaffold** and
overlaid only when opted in. The generator overlays `addons/<name>/common/`
(stack-agnostic) then `addons/<name>/<stack>/` (stack-specific) when the matching
`include_<name>` flag is `yes`.

| Add-on | Flag | What it ships | From |
|--------|------|---------------|------|
| `k8s` | `include_k8s` (default `no`) | Kustomize base + staging/production overlays per stack (Deployments/Services, ingress, secret example). Cloud-native: managed DB out-of-cluster, secrets out-of-band. **Not free-tier.** | sibling |
| `auth` | `include_auth` (default `no`) | Passwordless OTP sign-in for `fastapi-next`: models/store/flows/delivery/router + an auth-aware `main.py` + `docs/AUTH.md` + tests. In-memory default **or** a durable `PostgresAuthStore` (`AUTH_STORE=postgres` + `002_auth.sql`, psycopg3 async, no new deps). Ships a Next.js OTP sign-in widget (`auth-widget.tsx` + `layout.tsx`/`next.config.mjs` overlays). OAuth flow is a documented follow-up | sibling |
| `ssrf_fetch` | `include_ssrf_fetch` (default `no`) | Dependency-free SSRF-guarded server-side URL fetch (`app/services/safe_fetch.py`): http/https-only, resolves to public IPs only, re-validates redirects, size/time-bounded, stdlib HTML→text + offline tests + `docs/SAFE_FETCH.md` | sibling |
| `bug_report` | `include_bug_report` (default `no`) | In-app bug capture for `supabase-flutter`: `bug_reports` migration (deny-by-default RPCs) + a `dart:io` capture sheet/breadcrumb trail + dependency-free screenshot capture (`RepaintBoundary`) + a SQL-formatted `pull-bug-reports.sh` (→ `gh issue create`) + `docs/BUG_REPORT.md`. No new Flutter deps | sibling |
| `scheduled_agent` | `include_scheduled_agent` (default `no`) | **Stack-agnostic** (`addons/scheduled_agent/common/`): an opt-in "cloud session" — `scheduled-agent.yml` (dispatch by default, commented cron to go recurring, least-privilege `contents:read`/`issues:write`) + a dependency-free `scripts/agent-drop.mjs` (Node 20 `fetch`: Anthropic Messages API → opens a GitHub issue) + an editable `.github/agent/prompt.md` + `docs/SCHEDULED_AGENT.md`. Reuses the existing `ANTHROPIC_API_KEY`; no new deps | sibling (idea-drop) |

To include one: `./bin/firestart.sh --set include_k8s=yes` (or answer `yes` at the
prompt). To add a new add-on: create `addons/<name>/<stack>/` (or
`addons/<name>/common/` if it's stack-agnostic) whose contents **mirror the
project layout** (e.g. `addons/k8s/<stack>/k8s/base/...` lands at
`<project>/k8s/base/...`), add an `include_<name>` flag to
`firestarter.config.json`, and register `<name>` in the add-on loop in
`bin/generate.py`.

## Tokens

Declared in `firestarter.config.json` and substituted as `{{ key }}`:

| Token | Meaning |
|-------|---------|
| `project_name` | Human name, e.g. "Project Lighthouse" |
| `project_slug` | lowercase id; drives db name, container prefix, package names |
| `project_tagline` | one-liner used across docs |
| `github_owner` / `github_repo` | for secret/clone commands |
| `stack` | which profile to overlay (`fastapi-next` \| `supabase-flutter`) |
| `db_name` | defaults to `project_slug` |
| `commit_scopes` | allowed conventional-commit scopes |
| `require_coauthor` / `coauthor_footer` | whether commits need a co-author line |
| `claude_model` | default model for the AI reviewer |
| `port_db/redis/api/web` | offset host ports so stacks coexist |

**Derived** (computed by `generate.py`, no need to declare):
`migrations_table` (`<slug>_migrations`), `pgdata_volume`, `container_prefix`,
`coauthor_policy`, `coauthor_commit_footer`.

### Token safety
The generator replaces only the **exact declared keys**, so GitHub Actions
expressions like `${{ github.sha }}` are never touched — they aren't in the
whitelist.
