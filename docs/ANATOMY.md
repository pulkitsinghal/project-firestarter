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
  generate.py             stdlib generator; preserves declared executable bits
template/                 UNIVERSAL meta-layer — copied for every project
stacks/
  fastapi-next/           FastAPI + Next.js (fastapi-next lineage)
  supabase-flutter/       Supabase + Flutter + React (supabase-flutter lineage)
  chrome-extension/       Manifest V3 + TypeScript (browser-extension lineage)
  node-notifier/          Express + BullMQ + Redis + Socket.IO notification lab
addons/                   OPTIONAL modules, overlaid only when opted in
  k8s/<stack>/            Kustomize manifests (include_k8s=yes)
  kokoro_warm/common/     stack-agnostic narration audio standard (include_kokoro_warm=yes)
  orchestrator_session/common/  Bill + schema-1.4 capacity/lifecycle/federation control plane + repo-local PM-proxy plugin (include_orchestrator_session=yes)
  service_supervisor/common/    synthetic allowlisted lifecycle catalog/planner (include_service_supervisor=yes)
  browser_automation_policy/common/  semantic-first source policy and synthetic adapters (include_browser_automation_policy=yes)
prototypes/               OPT-IN reference implementations, not generator output
  operations-dashboard/   shared contract + offline sanitized publisher
  operations-dashboard-web/  static sanitized snapshot renderer
  operations-floater/     native macOS local dashboard
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
| `.gitignore` | Covers Python, Node, Dart/Flutter, Docker, storyboard output; ignores Claude Code **local** state (`.claude/settings.local.json`, `.claude/worktrees/`) while keeping the committed `.claude/settings.json` + hooks tracked | union of both |
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
| `docs/FEATURE_HANDOFF.md` | Evidence-bundle precept: exact acceptance/failure/recovery/verification; real storyboard/state-map evidence; normal-speed E2E story beats post-produced into narrated/captioned, focus-guided review media and release cuts when a reproducible harness exists; non-visual substitution rule | reusable sibling release workflow |
| `docs/ENGINEERING_CONVENTIONS.md` | Four reusable stack-neutral conventions the AGENTS brief points to: the authoritative quality gate (code review + the unit→integration→api→e2e pyramid, run locally, sufficient to merge, never a side-effect licence), stacked-PR merge order + recovery, forking discrete work into its own PR, and asking for decisions visually rather than as a wall of text | distilled cross-project engineering practice |
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
| `docker-compose.yml` | postgres (pgvector) + redis + backend + frontend; `tools`/`node`/`storyboard` profiles. The `backend-tools`/`frontend-tools` services **mount live source** over the baked image so test/lint/seed run against the working tree, not stale baked source |
| `Makefile` | `up/down/migrate/test/lint/precommit/storyboard/hook-install` + `frontend-lockcheck` — all via Docker |
| `scripts/sync_version.sh` + `make version-sync` | Propagate `/VERSION` into `backend/pyproject.toml` + `frontend/package.json` (host coreutils, no SDK) |
| `.github/workflows/ci.yml` | Jobs **Tests**, **Lint & Typecheck**, **Build** (names matched by auto-merge) |
| `backend/` | FastAPI app, `pyproject.toml` (ruff/mypy/pytest), `001_init.sql`, `scripts/migrate.sh`, a smoke test, and a hermetic-vs-integration test split (`make backend-itest` + `integration` marker + `tests/integration/` gated on `TEST_DATABASE_URL`). `GET /health` also reports **deploy provenance** (`built_at`/`git_sha`) baked into the image by `make up`, so you can verify which commit is live |
| `frontend/` | Next.js App Router skeleton with an `/api` proxy to the backend; exact patched dependencies are locked and installed with `npm ci` |
| `storyboard/` | Playwright runner pinned to `mcr.microsoft.com/playwright` |
| `.github/dependabot.yml` | Grouped weekly updates (pip + npm + github-actions), `chore:`/`ci:` prefixes |
| `DEPLOY.md` + `cloudflared` deploy profile | One-button Cloudflare quick-tunnel to expose the frontend publicly (no account); plus a **stable named-tunnel** runbook + `deploy/cloudflared/config.example.yml` template + `make tunnel` for a fixed hostname on your own domain (creds gitignored) |
| `storyboard/manifest.json` + render | Manifest-driven planned-vs-implemented map → committed `docs/STORYBOARD.md` |

### Documented gotchas baked into this stack
- **Stale baked source in the tools profile:** the build images bake source, so `backend-tools`/`frontend-tools` run the *last build's* code — after an edit, `make backend-test`/`seed` silently uses stale content until you rebuild. Fixed by mounting live source over `/app` (backend's editable install resolves `app` from the mount; frontend keeps its baked `node_modules` via an anonymous volume).
- **npm 10 vs 11 lockfile completeness (`EUSAGE`):** the `node:22` build image runs npm 10, which tolerates a `package-lock.json` missing other platforms' optional deps; a modern host runs npm 11, which rejects it and breaks local `npm ci`. `make frontend-lockcheck` (+ a CI step) re-resolves in a throwaway `node:24-alpine` so an incomplete lockfile fails loudly.

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
| `extension/` | MV3 skeleton: narrow manifest, side panel/background/content entry points, plus the cohesive `src/browser-assistant/` reference module for deterministic intent, exact accessible-label resolution, typed cross-world messaging, metadata-only audit, permission pinning, and fail-closed tests |
| `docs/BROWSER_ASSISTANT.md` | Durable choice guide for content scripts vs debugger/CDP vs native messaging, permission/profile handling, prompt-injection isolation, confirmations, retries/idempotency, audit/privacy, testing, real-toolbar acceptance, and Store policy |
| `e2e/` | Playwright MV3 harness: persistent headed Chromium, direct side-panel smoke, and a real compiled content-script check against a local hostile fixture (duplicate/ambiguous/hidden/unsafe cases). Xvfb makes it opt-in CI-capable; real toolbar attachment remains a distinct human release gate |
| `.github/workflows/e2e.yml` | **Opt-in** (`workflow_dispatch`) headed e2e on a display-less runner via Xvfb — least-privilege, a distinct job name, never a required gate. Closes the "wire an opt-in job once you have a runner with a display" TODO |
| `storyboard/` | Screenshots the built side panel (`dist/sidebar.html`) → committed `docs/STORYBOARD.md` (honours the storyboard precept for a UI with no server) |
| `tools/demo-recording/` | Records the **real** side panel as video (page + panel + cursor) with no login: iframe the live `sidebar.html` into a staged page, seed auth/data offline via the service worker, capture with Playwright `recordVideo`. A fill-in-the-blanks `record.template.mjs` + generic primitives (`visual_cursor_overlay.js`, `video_processor.py`) + a README of the hard-won gotchas. Complements `storyboard/` (stills) with a moving release/QA clip |

### Documented gotchas baked into this stack
- **esbuild doesn't type-check:** `tsc --noEmit` is a separate gate (the "Lint & Typecheck" job).
- **Per-page video misses the side panel:** to record the panel + cursor, iframe the live `sidebar.html` into one page and use Playwright `recordVideo` (not `ffmpeg x11grab`, which is black on a bare Xvfb). See `tools/demo-recording/README.md`.
- **No host SDKs, arm64 native deps:** node_modules lives in a named volume so the container builds esbuild's platform-specific binary, not the host's.
- **e2e is host-only:** loading an MV3 extension needs a real headed Chromium — a headless container can't, so it isn't a CI gate.
- **Direct extension pages are not toolbar-attached panels:** `chrome-extension://…/sidebar.html` can become the active tab and hide tab-association bugs. Keep a distinct branded-Chrome toolbar smoke; Playwright cannot reliably operate native extension toolbar/permission UI.
- **Page prose is data, never control:** the browser-assistant module accepts a bounded user grammar and resolves one exact visible safe link. Hostile page text cannot add commands, tools, permissions, or selectors.

## Stack profile: `node-notifier` (durable notification lineage)

A Redis-backed teaching stack with no relational database. `make migrate` is a
documented no-op because BullMQ owns its Redis key schema.

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Hardened API and worker containers plus network-private Redis 8; `test` and `storyboard` profiles. Only the loopback web port is published. |
| `Makefile` | Docker-only lifecycle, unit/integration gates, production image build, storyboard, cleanup, hooks, environment check, and version sync. Ordinary `down` preserves task state; `clean-data` is the explicit destructive path. |
| `.github/workflows/ci.yml` | Exact **Tests**, **Lint & Typecheck**, and **Build** display names. Redis-backed cross-instance tests run through the same Compose target used locally. |
| `src/` | Express 5 API, BullMQ worker, signed local sessions, provider-neutral OIDC JWT validation, tenant/user-derived opaque ownership, Redis-backed rate limiting, task index, and idempotent acknowledgement. |
| `public/` | Dependency-light browser lab: create a task, reconcile saved state after socket hints or reload, and mark a terminal result seen. |
| `test/` | Hermetic unit suite plus real-Redis coverage for two-API fan-out, missed-event recovery, retry exhaustion, tenant isolation, token refresh, acknowledgement replay, and distributed rate limiting. |
| `storyboard/` | Drives the real local API/worker path, captures ready → in-flight → completed → acknowledged, and regenerates the planned-vs-implemented map. |
| `docs/tutorial.md` | Guided failure experiments, checkpoints, cleanup, and a safe path for replacing the simulated worker operation. |
| `docs/production.md` | Explicit OIDC, Redis TLS/ACL, retention, rate-limit, WebSocket, MV3 client, deployment-gate, and rollback boundaries. |

### Documented gotchas baked into this stack

- **A socket is a hint, not state or identity:** BullMQ job state is
  authoritative; Socket.IO only prompts a refresh. The browser never submits a
  socket id as an authorization target.
- **Pub/Sub is not the work queue:** Redis Pub/Sub fans out low-latency update
  hints after the worker saves state. BullMQ holds retryable work durably.
- **Extension service workers suspend:** an MV3 client reconciles the REST task
  list on open/resume; it must not depend on a permanent background socket.
- **Local auth is not production auth:** anonymous signed cookies are
  loopback-only. Production startup requires HTTPS, validated OIDC tenant and
  subject claims, and `rediss://` with an ACL username and password.
- **Acknowledgement is narrowly defined:** it proves an authorized client
  called the endpoint; it does not prove a person understood or acted.
- **Redis 8 licensing is an owner choice:** the lab pins the unmodified official
  image, while redistribution and production selection remain a documented
  owner gate.

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
| `kokoro_warm` | `include_kokoro_warm` (default `no`) | **Stack-agnostic** (`addons/kokoro_warm/common/`): one narration audio standard for every narrated clip. A machine-readable `scripts/narration-audio.spec.json` (mono·48 kHz·-16 LUFS·-1.5 dBTP) that a dependency-free reader (`narration-spec.sh`) feeds to both the delivery masterer (`master-narration-audio.sh`: HP+limiter→48 k mono→2-pass loudnorm, copies video/subs bit-for-bit) and the CI guard (`check-narration-audio.sh` + `narration-audio.yml`), so encode target and gate can't drift. Plus a Warm Heart (Kokoro `af_heart`) `render-narration.sh` + `docs/NARRATION_VOICE_STANDARD.md`/`docs/KOKORO_WARM.md`. Because it's vendored, `sync-kokoro-warm.sh` (`--check` fails on drift) + a weekly `narration-audio-sync.yml` (opens one issue on drift) keep an adopting repo on the shared standard instead of forking it. No new deps | sibling (help-clip audio drift) |
| `orchestrator_session` | `include_orchestrator_session` (default `no`) | **Stack-agnostic** (`addons/orchestrator_session/common/`): `ORCHESTRATOR_BILL_OF_RIGHTS.md` is the one authoritative generic policy for scoped conversation-derived training, PM-proxy ownership, the mandatory root-role boundary, standing-decision launch envelopes, routine autonomy, bounded owner gates, visible queues and canonical repo/path ownership, read-only duplicate-stop and blocked-queue re-audit behavior, exact candidate→PR/merge→default evidence, truthful CI, atomic closure/refill sagas, calibrated worker-duration lanes, measured cleanup/resource return, privacy/identity/least privilege, and never-go-dark reporting. `ORCHESTRATOR_PROMPT.md` and `AGENTS.orchestrator.md` are thin pointers. `orchestrator-control/` adds a Python-stdlib-only schema-1.4 SQLite authority with stable policy IDs/schemas, an allowlist-only `root_role_guard.py` control-plane invariant that keeps root coordination-only while eligible workers exist and denies delegable inspection/design/code/test/estimate/deploy/cleanup work, transactional source/outcome/idempotency deduplication, owner claims/outbox, fences/receipts, exact expired-lease tombstones that release stale capacity without takeover/closure/archive/refill, objective-evidence lifecycle candidates, bounded handback checks and exact interrupt receipts, evidence-gated truthful status, typed decisions and handbacks, durable capacity-release events, receipt-derived slot truth, visible deficit/watchdog recovery, blocked recycling, duration control, and owner-operated single-leader federation with exact transfer receipts, disarmed-source-host gates, preserved subordinate capacity shards, and forward-only recovery after demotion. Receipt-feed 1.1 adds optional sanitized launch/handback public metadata, readable coarse labels/classes, evidence age, explicit 1.0 migration, idempotent caller-manifest bootstrap into canonical local state, and locked atomic content-addressed current/LKG publication for static dashboard incorporation without a hosted-to-Mac bridge. Duration envelopes use fixed `seconds` through `60m+` active-runtime buckets, separate queue/setup/tool/external wait and wall/evidence/close timing, reclassify underestimated workers without restart or ownership loss, learn only from bounded ≥5-sample coarse family/tool/environment evidence, age queues fairly, protect short lanes, cap heavyweight work, and keep queued setup reserved-not-active. The MCP layer supports an owner-private content pin across the exact control CLI, version, schemas, guard, and runtime verifier; automatic launch/refill remains disabled until that pin and a matching current-version covered dispatcher proof both exist. Authority transfer is excluded from MCP so an ORC cannot self-promote. The MCP surface cannot self-record dispatcher adoption: an owner-operated fixed bridge outside root-role execution must write the receipt after live proof, and status keeps unattended/universal control false. The opt-in Desktop host adapter proxies a separate app-server, binds one exact owner-selected task ID to the native hook guard through a private local attestation socket, keeps other task IDs as workers, requires a fresh no-side-effect live denial before launch, and leaves the normal Desktop app unchanged for recovery. Safe legacy migration, privacy-safe calibration, dashboard/CLI traces, and the Phase-2 agent-CLI wrapper contract are included. The guard and required lifecycle-reconcile cadence are source-only until an application/platform dispatcher interposes before every relevant tool/message/timeout/status claim; exact-master validation, repo/team adoption, and real dispatcher-denial/reconcile E2E are distinct proof stages. `.agents/plugins/marketplace.json` and `plugins/pm-proxy-orchestrator/` provide the validated repo-local source plugin without installing it. `decisions-board/` is a CSP/link-hardened compatibility view, never authority. Stdlib process tests plus every-stack generation contracts enforce the behavior. No owner-specific config/secrets, raw prompts/hashes, task identifiers/paths in calibration, third-party dependencies, network, or deployment | durable orchestrator policy + local enforcement |

Control bundle `1.4.2` and plugin `0.4.2` add truthful local-only and bounded
local-artifact closures, an exact receipt-fenced control-schema hold, one-claim
expired setup-failure poisoning, and typed owner-private decision routing to a
pinned sink without capacity or sink authority. The local artifact route stores
only canonical relative paths and SHA-256 transitions, verifies current content,
and rejects traversal, symlinks, duplicates, false transitions, delivery claims,
or incomplete cleanup. The hold uses a short-lived host-attested one-use grant
that is revoked before dispatch; it preserves task/receipt/claim/fence/lane and
accepts only its exact terminal replay. The Desktop proxy also stops and joins
stdio forwarding threads before interpreter finalization.

Control bundle `1.4.3` keeps state schema `1.4`, plugin `0.4.3`, and interface
`1.0` unchanged while repairing early schema-1.4 databases whose
`control_schema_holds` table predates the nullable `released_at` and
`release_handback_id` columns. Every connection checks the exact current schema
before hold reads, adds only missing release columns in one immediate
transaction, and leaves accepted holds, tasks, claims, fences, and capacity
unchanged. Current-schema connections remain read-only at the schema level.

Plugin `0.4.4` publishes that already-merged control `1.4.3` migration and its
operator documentation under a new package identity. The control bundle,
schema, and interface do not change; distinct manifest/server versions keep
source/cache parity, runtime pins, and adoption receipts from treating changed
plugin content as the earlier `0.4.3` artifact.

Control bundle `1.4.4` and plugin `0.4.5` repair terminal archive admission
without changing state schema `1.4` or interface `1.0`. An expired local-only or
local-artifact predecessor must still match its exact ticket, canonical thread,
policy/lease/fence identity, durable handback, released claim, terminal refill
outcome, and pending archive outbox. A setup-failed reserved successor can be
superseded only by the authoritative saga's exact receipted replacement. Exact
replay is idempotent; the repair never renews a lease or creates, relabels, or
releases tasks, claims, capacity, or successors.

Control bundle `1.4.5` and plugin `0.4.6` close the remaining real-ledger
replacement-chain gap without changing state schema `1.4` or interface `1.0`.
The bridge now joins the local and authoritative views by exact saga identity,
requires the superseded reservation to be failed with a poisoned create outbox,
and verifies the replacement's create receipt, claim fence, terminal lifecycle,
and archive outbox. A replacement that has already closed remains valid history;
an unrelated current capacity deficit does not erase its exact receipt. Missing,
mismatched, unreceipted, nonterminal, and unknown-failure chains remain denied.

The orchestrator Desktop host binds a process-local prompt-free grant to only
sixteen named typed control tools after exact runtime-pin, current-version
covered adoption, private-proof, and receipt-fence verification. The exact root
task is admitted; attested workers and shell, file, browser, Sites, expired-lease,
owner-gated, and universal paths remain outside that grant.

Control `1.4.2` retains the typed capacity tool and owner-operated
single-leader federation outside the MCP surface. Capacity reconfiguration
compares the expected current capacity and exact state revision before a bounded
change, refuses reductions below receipt-backed active/reserved occupancy, and
commits the capacity, revision, idempotency receipt, and audit event in one
SQLite transaction. It is unavailable until the exact runtime pin and current
covered-path adoption are verified and is not a direct database-edit escape.

The orchestrator control directory also contains an audit-only adaptive-capacity
companion. It deterministically evaluates one closed caller-supplied metrics
snapshot, but does not collect metrics, reserve/admit work, alter SQLite state,
or authorize service-supervisor actions.
| `service_supervisor` | `include_service_supervisor` (default `no`) | **Stack-agnostic** (`addons/service_supervisor/common/`): a Python-stdlib, source-only control-plane contract for exact allowlisted service IDs. The synthetic lifecycle slice rejects unknown fields/adapters/commands, validates dependency DAGs, emits deterministic wake/idle plans, and implements coalesced bounded readiness, leases, drain grace, dependency pins, rollback/crash cleanup, truthful unknown metrics, and content-free bounded telemetry. Version 0.2 pins the exact merged local-ai lifecycle-v1 schema/catalog/observations/plan/result fixtures, validates closed launchd/Compose/Ollama plan/result data without executing it, atomically consumes scope/generation/time-bound signed PM permit nonces, persists revocations, and emits only a separately signed short-lived handoff receipt with verifier/pin provenance and a broker-owned independent nonce. Apply and rollback use distinct authorization phases, PM nonces, and receipts. The local-ai inventory mapping preserves unavailable observations as unavailable and treats `managed:false` as no executor permission. A GET/HEAD broker appears only in tests to prove wake-before-forward and refusal behavior. Runtime source contains no listener, proxy, Docker socket, OS executor, subprocess, installation, network client, or host-state action; a later Caddy wake broker and real adapters require separate execution gates. | local service capacity architecture and observe-only inventory contract |
| `secret_vault` | `include_secret_vault` (default `no`) | **Stack-agnostic** (`addons/secret_vault/common/`): cross-platform redundant secret storage. `secret-store`/`secret-get`/`git-crypt-key` in both `scripts/*.sh` (macOS **Keychain** + Linux **secret-service**) and `scripts/*.ps1` (Windows **Credential Manager** via advapi32 P/Invoke + DPAPI backup) store every secret in **1Password (`op`) + the OS secret store + a locked on-disk backup**, cross-checked by **sha256 fingerprint** (fails closed under 2 verified copies). `secret-get --exec ENV -- cmd` injects at runtime (never argv/file); the value is never echoed/logged. Generalises the ad-hoc macOS-only `git-crypt-key-store`. Ships `docs/SECRET_VAULT.md` (concept/matrix/recovery/rotation) + `docs/SECRETS.md` (the house contract, wired into `template/AGENTS.md`). Dependency-light (`op`/`git-crypt` cross-platform); runs on the host, not Docker | a sibling (`git-crypt-key-store`) |
| `encrypted_local_areas` | `include_encrypted_local_areas` (default `no`) | **Stack-agnostic** (`addons/encrypted_local_areas/common/`): the "encrypted local areas in a git repo" convention, so a stamped project can hold sensitive local data in-repo and still be pushed/backed up. git-crypt transparently encrypts a designated area (`{{ encrypted_paths }}/`, default `private`) at rest via a **per-area** `.gitattributes` (`* filter=git-crypt diff=git-crypt`, with `README.md`/`.gitattributes` kept `!filter !diff` so the plaintext pointer stays readable while locked — nested so it never clobbers the template's top-level `.gitattributes`). A **fail-closed** `scripts/git-crypt-guard.sh` (pure `git` plumbing, needs no git-crypt binary) checks every staged blob under a git-crypt path for git-crypt's 10-byte magic header and refuses the commit if the key isn't loaded; it runs from a **superset** `.githooks/pre-commit` that keeps the base `make precommit` gate. A plaintext **pointer README** states the key lives in `{{ password_manager }}` + the OS keychain and the **no-public-remote** rule. `docs/ENCRYPTED_LOCAL_AREAS.md` is the setup/unlock/rotation runbook. Complements `secret_vault` (which stores/recovers the *key*); either works alone. Host-only (git-crypt is a host tool); no new deps | sibling encrypted-area convention (git-crypt) |
| `browser_automation_policy` | `include_browser_automation_policy` (default `no`) | **Stack-agnostic** (`addons/browser_automation_policy/common/`): version 0.1 Python-stdlib, source-only policy and semantic-adapter contract. It binds proposals to task/tab/document/frame/origin/generations and exact adapter/action/effect/target-contract digests, treats page instructions as untrusted data, enforces typed actions, pre/postconditions, action-bound confirmation, reversible draft plans, atomic in-process replay state, semantic DOM-first resolution, proposal-bound Relative XY fallback, separate Citrix/remote session controls, voice intent normalization without targeting authority, and content-minimized evidence. Closed schemas and executable synthetic adversarial fixtures cover hidden/overlaid/duplicate/stale/cross-origin/shadow/dynamic targets, prompt injection, replay, navigation races, and geometry drift. It emits only a short-lived nonce/idempotency-bound policy handoff marked `executorConfigured:false`; durable ledger consumption remains a future-executor obligation, and no extension, browser/profile access, input injection, screenshot/OCR, credential, network, observer, executor, or deployment is included. | 2026-07-28 public-source browser automation checkpoint, treated as untrusted design input |
| `local_ollama` | `include_local_ollama` (default `no`) | **Stack-agnostic** (`addons/local_ollama/common/`): the *generic* HTTP transport plumbing for a local `ollama serve` — the shape consuming projects otherwise hand-roll. Pin a model, POST a typed JSON body to `/api/generate` \| `/api/chat` \| `/api/embeddings` on `http://{{ ollama_host }}:{{ ollama_port }}`, decode a typed response, bound the timeout and response size, and raise a typed error for every failure mode. Ships a **Python** variant (`local-ollama/python/local_ollama_client.py`, stdlib `urllib` only) and a **Swift** variant (`local-ollama/swift/LocalOllamaClient.swift`, Foundation only), each with an offline mock/injected-transport self-test. **Loopback-first**: a non-loopback host is refused unless explicitly opted in; the default transport ignores env proxies and never follows a redirect, has no cache/cookies/credentials. Carries **no** prompts, domain schema, or vision/document/screen logic — that stays in the consumers. Tokens: `ollama_host`/`ollama_port`/`ollama_model`/`ollama_embed_model`. `docs/LOCAL_OLLAMA.md` is the usage + safety doc. No new deps | duplicated local-model HTTP transport across sibling consumers |

### Orchestrator partial-activation gotcha

| File | Purpose |
|------|---------|
| `plugins/pm-proxy-orchestrator/.codex-plugin/plugin.json` | Explicitly binds `mcpServers` to `./.mcp.json`; Codex can discover the default hook file without this pointer, so omitting it can activate root denial before reservation tools exist. |
| `plugins/pm-proxy-orchestrator/.mcp.json` | Exact bounded stdio server definition for the typed `pm_proxy_*` control surface. The plugin source scan and stamping contract pin it byte-for-byte. |

The add-on deliberately contains no `.codex/hooks.json`: stamping policy must
not arm the trusted root role. Installation, MCP discovery and typed `doctor`,
exact hook trust, role activation, and live adoption are separate ordered gates.
If a root hook fires without callable `pm_proxy_*` tools, restore the prior
project hook state outside that blocked task and restart before retrying.
The pre/post hook ledgers use bounded nonblocking private locks; observations
record debt before dispatch, terminal admissions are pruned from authoritative
tickets, and an archive receipt permanently removes archive eligibility.

To include one: `./bin/firestart.sh --set include_k8s=yes` (or answer `yes` at the
prompt). To add a new add-on: create `addons/<name>/<stack>/` (or
`addons/<name>/common/` if it's stack-agnostic) whose contents **mirror the
project layout** (e.g. `addons/k8s/<stack>/k8s/base/...` lands at
`<project>/k8s/base/...`), add an `include_<name>` flag to
`firestarter.config.json`, and register `<name>` in the add-on loop in
`bin/generate.py`.

## Opt-in operations-dashboard prototypes

These directories are reusable references in the Firestarter repository, not
generator overlays:

| Path | What it demonstrates | Privacy boundary |
|------|----------------------|------------------|
| `prototypes/operations-dashboard/` | Version `1.0` contract and an offline, content-addressed sanitized publication workflow | No endpoint, URL, host, IP, path, credential, identity, or live-value fields in the shared model |
| `prototypes/operations-dashboard-web/` | Compact one-shot renderer with a dense synthetic ten-lane lifecycle view, resource/test/privacy evidence, responsive breakpoints, executable validator tests, and rebuilt browser frames | Rejects non-sanitized records, private-looking values, and unknown fields; renders text without HTML interpolation; no polling or workstation bridge |
| `prototypes/operations-floater/` | Single-Space macOS floater with local snapshot import, collapsible inactive cards, reversible local snapshot updates, sortable race lanes, optional loopback Router chat, a dismissible companion, and an on-device voice conversation backed by a bounded synthetic conversation module | Reads local state only; local-only records must be verified; chat is default-off, fixed-loopback, non-persistent, and attaches no dashboard state; conversation modules remain allowlisted, transactional, ephemeral, and non-replayable |

The contract represents queue, tests, resource budget, and signals as record
arrays. Every record declares exposure and verification so unrun tests,
unavailable telemetry, and scheduling estimates remain visibly distinct.
[`docs/OPERATIONS-DASHBOARD.md`](OPERATIONS-DASHBOARD.md) contains the usage,
validation, publication, and rollback runbook.

## Tokens

Declared in `firestarter.config.json` and substituted as `{{ key }}`:

| Token | Meaning |
|-------|---------|
| `project_name` | Human name, e.g. "Project Lighthouse" |
| `project_slug` | lowercase id; drives db name, container prefix, package names |
| `project_tagline` | one-liner used across docs |
| `github_owner` / `github_repo` | for secret/clone commands |
| `stack` | which profile to overlay (`fastapi-next` \| `supabase-flutter` \| `chrome-extension` \| `node-notifier`) |
| `db_name` | defaults to `project_slug` |
| `commit_scopes` | allowed conventional-commit scopes |
| `require_coauthor` / `coauthor_footer` | whether commits need a co-author line |
| `claude_model` | default model for the AI reviewer |
| `port_db/redis/api/web` | offset host ports so stacks coexist |
| `encrypted_paths` | encrypted-local-area directory (default `private`); used by the `encrypted_local_areas` add-on |
| `password_manager` | password manager the git-crypt key lives in (default `1Password`); used by `encrypted_local_areas` |
| `ollama_host` / `ollama_port` | local Ollama server address (default `127.0.0.1` / `11434`); used by the `local_ollama` add-on |
| `ollama_model` / `ollama_embed_model` | pinned local generate/chat and embeddings models (default `llama3.2` / `nomic-embed-text`); used by `local_ollama` |

**Derived** (computed by `generate.py`, no need to declare):
`migrations_table` (`<slug>_migrations`), `pgdata_volume`, `container_prefix`,
`coauthor_policy`, `coauthor_commit_footer`.

### Token safety
The generator replaces only the **exact declared keys**, so GitHub Actions
expressions like `${{ github.sha }}` are never touched — they aren't in the
whitelist.
