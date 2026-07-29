# Changelog

All notable changes to the firestarter template. See
[docs/LIFT-LOG.md](docs/LIFT-LOG.md) for the harvesting process.

## [Unreleased]

### Added
- Operations Floater 1.1.0 (build 2) permission/install lifecycle: a read-only
  designated-requirement compatibility preflight, helper-free bundle audit,
  one-instance recorder host, transactional **Give floor** rollback, and
  synthetic tests that never sign, install, launch, or request TCC access.
  Routine validation is bundle-free on the active macOS profile because Xcode
  26.5 still invokes `lsregister` despite
  `REGISTER_WITH_LAUNCH_SERVICES=NO`; XcodeGen source now retains both the
  `AppIcon` plist and asset-compiler declarations.
- Unified operations-dashboard reference sources under `prototypes/`: a strict
  privacy-neutral contract, native macOS floater with validated local snapshot
  import/rollback, sanitized static web renderer, and offline content-addressed
  publication workflow with tamper, update, HTTP retrieval, and rollback tests.
  Regular-file and one-megabyte input limits, last-mile browser privacy checks,
  and compensating release rollback fail closed. The prototypes are opt-in
  references and are not stamped by the generator.
- `include_orchestrator_session` add-on (stack-agnostic): one canonical, generic
  `ORCHESTRATOR_BILL_OF_RIGHTS.md` for scoped conversation-derived policy
  precedence, PM-proxy ownership, routine delivery, bounded owner gates,
  standing-decision launch envelopes, canonical repo/path ownership, read-only
  duplicate-stop behavior, blocked-work re-audits before lower-value
  replenishment, exact candidate-to-default evidence, truthful zero-step/billing
  CI semantics, closure/successor lifecycle transactions, measured
  cleanup/resource return, privacy/identity/least privilege, and never-go-dark
  reporting. The bootstrap prompt and agent addendum are thin pointers; a stdlib
  CI contract stamps every declared stack, byte-compares the generated Bill to
  its source, and pins the failure-prevention clauses.
  Also ships the dependency-free `decisions-board/` queue/status view and
  `docs/ORCHESTRATOR_SESSION.md`. No owner-specific config, dependencies, host
  toolchain, or network calls.
- `include_secret_vault` add-on (stack-agnostic): cross-platform redundant secret
  storage (`secret-store`/`secret-get`/`git-crypt-key` in `.sh` for macOS Keychain
  + Linux secret-service and `.ps1` for Windows Credential Manager + DPAPI). Every
  secret is stored in 1Password + the OS secret store + a locked on-disk backup and
  cross-checked by sha256 fingerprint (fails closed under two verified copies);
  runtime use streams the value straight into the consumer, never argv/logs.
  Generalises the ad-hoc macOS-only `git-crypt-key-store`. Ships `docs/SECRET_VAULT.md`
  + a `docs/SECRETS.md` house contract wired into `AGENTS.md`.
- A two-speed E2E handoff precept: tests capture asserted story beats and focus
  targets at normal speed, while narration, captions, pacing, effects, and media
  validation happen only in post-production.
- A generated-project media policy that commits compact polished release masters
  and optional GIF previews under `docs/media/`, while raw E2E recordings remain
  CI artifacts and larger media uses release attachments or Git LFS.
- Evidence-backed feature handoffs in generated agent/human guidance and PR
  templates: exact acceptance, failure/recovery, rollback, and verification
  evidence; real storyboard/state-map evidence for visible work; full E2E
  rehearsal evidence when available; and 20–40s narrated/captioned,
  focus-guided release cuts with natural voice when a reproducible repository
  harness exists.
- One-workstation local-CA policy and verified rollout/rollback guidance for
  generated projects. (#9)

### Changed
- Self-CI now proves that examples cover every declared stack and stamps all of
  them, including `chrome-extension`, before merge.
- FastAPI/Next Docker builds use cache-friendly ordering and BuildKit cache
  mounts. (#7)
- FastAPI/Next dependency installs are lockfile-reproducible and use patched
  Next.js/PostCSS versions with a zero-finding production audit. (#10)

### Fixed
- Made the documented and self-CI token-leak gate ignore binary storyboard
  assets so image bytes cannot produce a false token-leak failure.

## [0.2.0] — 2026-07-06

Everything landed since `0.1.0` via the self-hosted AI-reviewed auto-merge
pipeline. See [docs/LIFT-LOG.md](docs/LIFT-LOG.md) for provenance (which sibling
each learning came from).

### Added
- **Third stack profile `chrome-extension`** — Manifest V3 + esbuild + Vitest +
  host-only Playwright e2e + a side-panel storyboard. The first **DB-less** stack
  (adapts the DB-centric meta-layer; `make migrate` is a documented no-op). (#40)
- **Opt-in add-ons** (`include_<name>`, all default off):
  - `auth` (fastapi-next) — passwordless OTP sign-in: in-memory **or** a durable
    `PostgresAuthStore` (`AUTH_STORE=postgres`, psycopg3 async, no new deps) + a
    Next.js OTP sign-in widget. (#26, #29, #31)
  - `bug_report` (supabase-flutter) — in-app capture → deny-by-default RPC →
    `gh issue create`, with dependency-free screenshot capture. (#27, #30)
  - `ssrf_fetch` (fastapi-next) — SSRF-guarded server-side URL fetch
    (public-IP-only, redirect re-validation, size/time bounds, stdlib HTML→text). (#35)
  - `scheduled_agent` (**stack-agnostic**) — an opt-in "cloud session":
    dispatch/cron workflow + dependency-free `agent-drop.mjs` (Anthropic Messages
    API → opens a GitHub issue). Introduced the `addons/<name>/common/` overlay so
    a stack-agnostic add-on lives in one place. (#47)
- **Deploy**: dispatchable self-hosted `deploy.yml` (Cloudflare quick-tunnel, no
  secrets) (#20); a Supabase edge-functions deploy workflow that reads
  `vars.SUPABASE_PROJECT_REF`, auto-discovers functions, and self-skips until
  configured so a fresh stamp stays green (#48).
- **SemVer + version-sync**: canonical `/VERSION`, Keep-a-Changelog seed, and a
  per-stack `make version-sync` (host coreutils, no SDK). (#16)
- **CI/testing**: the Flutter app's tests now run in the Tests job (#19); a
  hermetic-vs-integration test split for fastapi-next (`make backend-itest` +
  `integration` marker gated on `TEST_DATABASE_URL`). (#34)
- **Agent brief**: end every response with a **repo + environment URLs footer**,
  backed by a single-source-of-truth Environments & URLs table. (#56)
- **Docs / runbooks**: migration-rollback (#18), go-live (#22), compliance-posture
  (#23), RPC catalog (#24), remote-agent-access spec (#28), host-requirements (#37),
  and a deploy self-authorization policy (#51).
- **Gotchas baked in**: GoTrue fresh-volume bootstrap so the supabase stack boots
  on an empty volume (#33); splash HMR file-watch polling over Docker bind mounts (#38).
- Landing page: a self-maintaining "last updated" date + a changelog link in the hero. (#57)

### Changed
- Elevated **storyboarding** from a documented merit to a stated **precept**:
  hard rule #6 in `AGENTS.md` (every stack ships a working storyboard harness) plus
  a "keep it current" precept and domain-invariant in `template/AGENTS.md`. (#12)
- **Least-privilege `permissions: contents: read`** on every read-only workflow —
  caps the `GITHUB_TOKEN` blast radius; write workflows keep their scopes. (#36)
- **CI cost**: `concurrency: cancel-in-progress` across the suite (except
  auto-merge, which is unsafe to cancel mid-merge). (#21)
- **Auto-merge by default (opt-out)**: `auto-merge-label.yml` auto-applies the
  `auto-merge` label to every non-draft PR; hold one back with a draft or `hold`. (#50)
- Recommend a **git worktree per concurrent session** in both AGENTS briefs. (#49)
- Refreshed the landing page for the third stack + the add-ons. (#41)

### Fixed
- Put pytest's rootdir on `sys.path` so a fresh fastapi-next stamp passes the
  Tests job. (#46)
- Made the supabase RPC deny-by-default grant actually effective (global form). (#17)
- Made fastapi-next `main.py`'s `DATABASE_URL` ruff-format-stable. (#32)

### Security
- **Deny-by-default RPC EXECUTE** in the supabase stack: revoke the implicit
  `PUBLIC`/`anon` grant so PostgREST doesn't expose functions until opted in. (#15, #17)
- **No default/guessable secret in deploy configs** (fail-closed, read from env) (#25);
  read GoTrue's JWT secret from env instead of a hardcoded default (#39).
- **Secret-rotation tool** (`make rotate-secrets`, supabase): mint a fresh
  `JWT_SECRET`/`DB_PASSWORD` + matching role JWTs off the dev default into a
  gitignored `.env.deploy` (chmod 600); JWTs minted in a throwaway container. (#52)

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
- **Stack profile `fastapi-next`** (fastapi-next lineage): compose, Makefile,
  CI, FastAPI backend + migrations + tests, Next.js frontend, Playwright
  storyboard.
- **Stack profile `supabase-flutter`** (supabase-flutter lineage): Supabase-style
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
