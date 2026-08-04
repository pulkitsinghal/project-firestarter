# Changelog

All notable changes to the firestarter template. See
[docs/LIFT-LOG.md](docs/LIFT-LOG.md) for the harvesting process.

## [Unreleased]

### Added
- ORC truthful local closure and decision routing: control bundle `1.4.2` and
  PM-proxy plugin `0.4.2` add exact local-only/local-artifact handbacks,
  content-verified privacy-safe SHA-256 manifests, receipt-fenced schema holds,
  one-claim expired setup-failure repair, and typed owner-gate routing to one
  pinned private sink without reserving capacity or granting sink authority.
  One-use bootstrap recovery, strict replay/tamper/cleanup checks, and named
  fence 38/41/42 plus P940 synthetic regressions keep the new paths fail closed.
- PM-proxy stdio shutdown fencing: forwarding threads stop cooperatively and
  are joined before interpreter finalization, including when Desktop leaves
  stdin open after the child app-server exits, preventing Python's buffered
  reader finalization abort.
- PM-proxy Desktop launcher hardening: the repository adapter now passes its
  owner-private Electron data directory as an explicit command-line switch
  before macOS single-instance selection, records that exact isolation value,
  and requires it while observing and stopping the exact Desktop PID. Missing
  isolation or proxy observation disarms and terminates only the spawned child;
  capability/session values remain private and the ordinary Desktop recovery
  instance is never a shutdown target.
- PM-proxy exact-root Desktop approval grant: after current-version covered-path
  adoption and runtime-pin verification, the isolated app-server pre-approves
  only the named typed doctor/status/runtime, launch-receipt, heartbeat,
  lifecycle, close/refill, archive/refill, slot-status, and watchdog controls.
  Other task IDs are denied that prompt-free surface, while task-domain tools,
  expired-lease reconciliation, owner gates, and universal enforcement retain
  their existing approval or denial behavior.
- PM-proxy runtime pin and automatic-control gate: one owner-private content
  digest binds the MCP server to the exact control CLI, version, schemas,
  root-role guard, and runtime verifier. Doctor/status/recovery remain
  bootstrap-safe, while new launch and refill mutations require both the pin
  and a current-version covered-path dispatcher-adoption receipt. Status never
  upgrades this bounded proof into universal platform enforcement.
- PM-proxy exact expired-lease retirement: a closed ticket-derived request can
  invalidate the stale fence, expire its owner claim, and release capacity
  without takeover, extension, handback, closure, archive, successor creation,
  or refill. Explicit-clock status distinguishes the durable `EXPIRED`
  tombstone from unknown-clock and no-active-claim states.
- PM-proxy under-capacity exact replacement: a clean terminal handback may
  atomically exchange its receipt-backed predecessor for one fenced successor
  even when other configured slots are already idle. The transaction snapshots
  and preserves pre-release occupancy, keeps full-capacity and EMPTY behavior,
  treats only the exact reserved successor as satisfying the saga, and leaves
  unsupplied idle slots visible without misclassifying the reserved candidate
  as still runnable.
- PM-proxy partial-activation protection: the plugin manifest now explicitly
  binds its typed MCP server, static validation pins the exact server definition,
  and the orchestrator overlay is forbidden from stamping an already-armed root
  hook. Adoption and rollback docs require hook-untrusted MCP discovery before
  the trusted root role is enabled.
- PM-proxy hook deadlock hardening: pre-dispatch lifecycle intent, bounded
  nonblocking private locks, authoritative stale-admission pruning, terminal
  archive replay rejection, and adversarial contention/exhaustion fixtures keep
  lock or ledger failure inside the hook deadline without silently dispatching.
- Checked-in orchestrator root/spawn runtime defaults (a coordinator model,
  reasoning effort, and priority service tier), plus a read-only machine/project
  startup verifier. It rejects untrusted projects, config or launch drift,
  API-key priority-tier claims, and unattested/contradictory tier provenance;
  desktop-app config proof is reported as `config-verified`, never
  runtime-attested. PM bridge ticket 1.3 carries the required runtime policy and
  launch attestation into the exact receipt boundary.
- Orchestrator-control schema 1.3 lifecycle watchdog: objective
  tests/output/closure evidence creates a durable `COMPLETION_CANDIDATE`
  independent of worker self-report; fresh typed remaining-work progress is
  bounded; two missed handback checks emit `TERMINALIZE` and
  `INTERRUPT_REQUIRED`; and an exact interrupt receipt atomically releases,
  re-audits, reserves a successor or proves `EMPTY`/`OWNER_GATED`, and starts
  the archive fence. Status exposes required reconciliation after worker
  messages, wait timeouts, and before claims. Interface 1.0 and existing
  schema-1.x state remain compatible.
- Audit-only adaptive-capacity evaluation for the orchestrator control plane:
  closed caller-supplied snapshot schemas, deterministic age/cap/digest
  computation, explicit non-authority flags, and a pinned service-supervisor
  inventory boundary. It does not collect host metrics, reserve or admit work,
  change scheduler state, or authorize service lifecycle actions.
- `include_browser_automation_policy` (default `no`), a stack-agnostic,
  Python-stdlib, source-only policy and semantic-adapter contract. Version 0.1
  binds typed proposals to task/tab/document/frame/origin generations; treats
  page instructions as data; enforces pre/postconditions, confirmation tiers,
  reversible draft plans, atomic in-process ledger state plus a durable
  exactly-once executor contract, content-minimized
  evidence, and short-lived future-executor handoffs. Semantic DOM is first,
  Relative XY is a trained bounded fallback with proposal-bound geometry, and
  Citrix/remote plus voice intent remain separate adapters. Closed schemas and
  rich synthetic adversarial
  fixtures cover stale, hidden, overlaid, duplicate, cross-origin, shadow,
  dynamic, injection, replay, race, and geometry/session drift cases. It ships
  no browser extension, profile/session access, input injection, screenshot/OCR,
  credential, network, observer, executor, or deployment path.
- Receipt-feed 1.1 operational bootstrap: optional bounded sanitized
  launch/handback `public_metadata`, readable `publicLabel` plus coarse
  `ownerClass`/`laneClass`, lifecycle-derived safe actions, evidence-age
  availability, explicit 1.0 migration, and a privacy-safe synthetic
  current-task manifest. A locked idempotent reconcile command now creates the
  canonical local state directory without agent-API scraping or raw payload
  persistence; a one-way atomic publisher emits deterministic content-addressed
  dashboard bytes plus current/LKG/previous pointers with rollback and
  concurrent-writer coverage. No hosted-to-Mac control bridge is introduced.
- `include_service_supervisor` (default `no`), a stack-agnostic, source-only
  supervisor contract for explicitly allowlisted loopback services. It ships a
  strict synthetic adapter, dependency DAG, deterministic wake/idle plans,
  `STOPPED`/`STARTING`/`READY`/`DRAINING`/`FAILED` lifecycle, concurrent wake
  coalescing, bounded readiness, dependency-aware leases and pins, rollback and
  crash cleanup, truthful unknown metrics, privacy-safe telemetry, a
  local-ai inventory mapping, and an operator runbook. The runtime has no data
  plane, listener, Docker socket, host executor, install step, or live service
  action; the GET/HEAD wake-before-forward contract exists only as a synthetic
  test fixture.
- Service-supervisor 0.2 typed permit verification: exact merged local-ai
  lifecycle-v1 plan/result and fixture pins; closed launchd/Compose/Ollama data
  shapes; deterministic plan hashing; signed, scope/generation/time-bound PM
  permits; durable atomic nonce consumption/revocation; and separately signed,
  short-lived broker handoff receipts with verifier/pin provenance and an
  independent broker-consumed nonce. Apply and rollback require distinct
  permits and receipts. The add-on remains default-off and contains no broker,
  listener, OS executor, subprocess, Docker socket, network client, or host
  service action.
- `pm-proxy-orchestrator` 0.2.0 as a repo-local source plugin and marketplace:
  fail-closed Firestarter interface checks, mandatory recycle/preflight,
  prompt-free launch tickets, exact receipt/fence enforcement, typed decision
  routing, and a crash-recoverable closure/refill wrapper with synthetic task
  tools, adversarial/privacy gates, and 100-repeat concurrency coverage.
- Orchestrator-control schema 1.2 capacity and duration sagas: clean
  `completed`/`archived`/`interrupted/notLoaded` normalization, durable
  `CAPACITY_RELEASED`, atomic successor reservation, receipt-fenced archival,
  visible runnable-capacity deficits, event-driven reconciliation, and periodic
  watchdog recovery. Interface 1.0 remains compatible and schema 1.0/1.1 state
  migrates in place.
- Duration-calibrated delegation lanes with exact `seconds` through `60m+`
  active-runtime bounds, versioned estimate metadata in every launch
  envelope/receipt, and separate queue/setup/active/tool-wait/external-wait/
  total-wall/first-evidence/safe-close observations. Receipt-backed workers
  reclassify to longer lanes without restart or ownership loss at the next
  boundary, >2x error, or a two-bucket skip; early finishes improve shorter
  evidence. Learned priors use only a bounded 20-sample coarse
  task/tool/environment window, require at least five consistent completions,
  and fail closed on sparse/conflicting evidence.
- Duration-aware scheduling ages work fairly, protects available short-lane
  capacity, caps `45m`/`60m+` concurrency, distinguishes queued-setup
  reservations from active receipt-backed workers, and excludes rolled-back
  setup failures before immediate next-candidate selection. The verified
  privacy-safe seed aggregate (SHA-256
  `c3739bb1abff972ba6a85ecacfd9b794c6843d972b2ff90320b7eef67030585a`)
  is below the learned-prior threshold and stores no raw prompt/hash,
  identifier, title, path, URL/email, PHI/private content, secret, command,
  diff, or output.
- Receipt-backed external identity reconciliation: only the canonical external
  task ID may heartbeat, mutate, hand back, or occupy capacity; platform-created
  mirrors receive deterministic read-only stop, zero-change handback, and
  archive instructions, and do not appear as dashboard owners.
- Mandatory `ROOT_ORCHESTRATOR_ROLE` preflight: an allowlist-only,
  privacy-bounded guard keeps root on owner-intent, launch/deduplication,
  decision routing, monitoring, refill, and worker-evidence synthesis. It
  denies root repository inspection, design, code, tests, estimation,
  deployment, cleanup, premature completion claims, and receiptless capacity
  fill with explicit successor/evidence requirements. This is a control-plane
  invariant rather than prompt etiquette: eligible worker capacity keeps root
  coordination-only and missed delegation cannot authorize direct work. Its
  only exception is an exact action/scope-bound `ROOT_EXECUTION_EXCEPTION` for
  nondelegable recovery with zero eligible workers,
  `SYSTEM_NONDELEGABLE_RECOVERY` authority, and a ≤300-second lifetime. Runtime
  enforcement is explicitly deferred to dispatcher interposition before every
  relevant tool; source
  validation, repo/team adoption, and a real dispatcher-denial E2E are separate
  evidence stages.
- Operations Floater 1.1.0 (build 2) permission/install lifecycle: a read-only
  designated-requirement compatibility preflight, helper-free bundle audit,
  single-instance app host, transactional **Give floor** rollback, and
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
  its source, pins the failure-prevention clauses, and exercises the generated
  machine interface. Also ships a Python-stdlib local control plane: versioned
  policy rules and JSON schemas, SQLite `BEGIN IMMEDIATE` authority, unique
  source/outcome/idempotency keys, transactional canonical owner claims and
  create/archive outbox, monotonic fencing and launch receipts, typed PM-proxy/
  owner-gate classification, atomic handback/successor intent, blocked-queue
  recycling, privacy-safe legacy migration, effective-rule/status visibility,
  and a Phase-2 agent-CLI skill/plugin integration contract. Process tests repeat
  the duplicate reservation race 100 times and cover crash rollback/recovery,
  stale-worker rejection, scoped precedence/conflict quarantine, literal
  zero-step CI, non-owner legacy import, local-state privacy, and unsafe-link
  rejection. The compatibility decisions board now has CSP and HTTP(S)-only
  links. No owner-specific config, third-party dependencies, network calls, or
  external deployment.
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
