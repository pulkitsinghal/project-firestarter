# Lessons — engineering practices that seed a new project

Hard-won practices distilled from real projects, generalized so a new repo starts
with them already in mind. Each is a reusable pattern plus the one-line reason it
exists. They pair with [LIFT-LOG](LIFT-LOG.md) (how fixes flow back into the
template) and [ANATOMY](ANATOMY.md) (where each piece lives).

---

## CI, branching & landing

**Docker-gate every toolchain behind a single `make` target.** Run all quality
gates (test/lint/format/typecheck/migrate) inside Docker via Compose profiles and
Makefile targets, exposed through one `make precommit` that mirrors CI — so
contributors and CI need zero host SDKs and "green before push" is reproducible
anywhere. Use *named* (not anonymous) volumes for dependency caches so they
persist across `docker compose run`. Carve out and document the genuine
exceptions where the host SDK is required — native platform builds and GPU-bound
work the Docker engine can't reach (e.g. Metal/MPS on macOS).

**Validate the exact CI check-set locally before pushing; branch first.** Run the
same checks CI runs, in the same containers, before every push — "push to see if
CI catches it" is an anti-pattern that burns slow round-trips. In-place
formatters may not exit non-zero on changes, so inspect the working-tree diff and
commit the reformatted files rather than trusting the format command's exit code.
Always create a feature branch before starting work; never commit on the default
branch.

**Enforce git hooks locally when hosted CI is unavailable, with a Docker escape
hatch.** Commit `.githooks/` (commit-msg = Conventional Commits, pre-commit =
typecheck + tests on staged files, pre-push = full suite) and auto-install them
via an npm `prepare` script that sets `core.hooksPath`. In Docker-only repos the
host hooks fail on an empty `node_modules` ("command not found") — that is *not* a
real failure; verify in the container and bypass with `--no-verify`, documenting
the bypass in the hook itself.

**Make the AI-review + auto-merge pipeline portable across stacks.** Standardize
CI job display names across heterogeneous stacks (Tests / Lint & Typecheck /
Build) so one auto-merge workflow is portable, and treat that job-name set as a
contract when adding a stack. Gate the squash-merge on an explicit label plus
green required checks, and have the workflow self-check the required checks so it
works even where branch protection is unavailable (free private repos). Recognize
a billing block — jobs failing in ~2 seconds on a spending-limit message — as an
account-level condition, not a code bug.

**Deny blanket git staging to protect concurrent sessions.** When multiple
agents or developers share one clone, commit repo settings that *deny* blanket
staging (`git add -A`/`.`, `git commit -a`/`-am`), require explicit-path staging,
and do all history surgery and builds in isolated `git worktree`s. Ignore
`node_modules` without a trailing slash so a worktree-symlinked `node_modules`
can't be staged. Before committing a dirty tree, `git fetch` and diff against
origin — work merged from another worktree can sit byte-identical-but-uncommitted
in a checkout that's behind origin.

---

## Database & migrations

**Write migrations idempotent, forward-only, and expand/contract.** Track
migrations forward-only in a dedicated table keyed by filename; write each one
idempotent (`DROP … IF EXISTS`, `CREATE OR REPLACE`, `IF NOT EXISTS`, seed via
`INSERT … WHERE NOT EXISTS`) so it re-applies cleanly to an existing schema — a
schema dump/restore path is for a *fresh* database only. Ship additive (expand)
changes first so the running app stays compatible, and never co-ship a
destructive `DROP`/`RENAME` with app code that depends on the old shape. Design
for asymmetric rollback: the frontend can roll back instantly, but the DB is
forward-only.

**Know the PostgREST/Postgres RLS & function gotchas.** On PostgREST-fronted
Postgres: an RLS `USING` policy alone still 401s until you also `GRANT` on the
base table (the privilege is checked before the policy), while `SECURITY DEFINER`
RPCs own their own access. Function identity is by argument *type*, not parameter
name, so `DROP` the function before renaming a same-type param or you silently
duplicate it. Pin `search_path` on functions and set `security_invoker=on` on
views to close latent RLS-bypass exposure, and reload the schema cache
(`NOTIFY pgrst, 'reload schema'`) after any signature change or clients 404. Ship
the migration to the environment *before* the client build that calls the new
signature, and default new params so old clients keep working.

**Realign a volume-baked DB password non-destructively.** A local Dockerized
Postgres bakes its role password into the data volume on first init; later
editing the env password (or running Compose from a worktree with no env file,
falling back to a default) crash-loops password-auth on the dependent services
when they restart. Fix it with `ALTER USER … WITH PASSWORD` — don't wipe the
volume.

**Add a gated Postgres integration suite for FK-blind unit tests.** If the
default unit/functional suite runs against an in-memory repository with no
foreign-key constraints, FK bugs pass tests but 500 in production. Add an
integration suite marked and gated on an env DB URL that runs against a real
migrated Postgres, tearing down rows in FK-dependency order (child-first) so it
self-cleans.

---

## Deploy & verification

**Deploy safe-by-default: preview → verify → promote → auto-rollback — never the
DB.** Publish to a preview URL, assert the expected build hash/config is actually
baked in, promote, verify production, and auto-rollback the frontend on failure
with an alert. Never auto-rollback the DB — a bad migration is the one thing
rollback can't undo; keep it manual and rely on expand/contract migrations so the
old frontend stays compatible during the window.

**Keep an append-only deploy/verify ledger of fingerprints only.** Persist a
git-tracked, append-only JSONL log of every deploy and verification, recording
credential *fingerprints* only (issuer/ref/last4) and never secret values, then
render it to a human-readable env×component status matrix.

**Verify static-asset presence by Content-Type, not status code.** A single-page
app's `/* /index.html 200` fallback makes every missing path return HTTP 200
`text/html`, so a status-code check can't tell "asset present" from "asset
removed" — check the Content-Type instead.

**CORS is browser-only, so verify like a browser.** A curl health-check passes
while a browser is CORS-blocked (curl ignores CORS), so a cross-origin asset check
must send an `Origin` header and fail if the response lacks
`Access-Control-Allow-Origin`. Also: public dev/test object-storage endpoints are
typically rate-limited and *not* edge-cached — bind a custom domain routed through
the CDN for production asset serving.

**Turn each recurring stale-state failure into a fail-loud preflight assert.**
Add a cheap assert at the single chokepoint where a real failure happened or is
one typo away: assert the working tree is at `origin/HEAD` before deploy; curl the
target's health from the run's network context before an E2E; make the deploy
refuse to publish unless the baked bundle matches the target env with no localhost
leak. A guard is the active complement to a passive note.

**Prove your scanner on known-dirty *and* known-clean fixtures.** Never trust an
aggregate "zero findings" from an ad-hoc shell regex — a `grep -P` compound regex
can fail silently and false-report clean, and a scanner pointed at a directory it
doesn't handle scans 0 files and passes green (nearly shipping a leaked key). Use
a dedicated, dir-aware, all-file-type scanner and prove it on both a known-dirty
and a known-clean fixture first. Verify demo outcomes by looking at an extracted
frame, not a log line.

---

## Config & secrets

**Split config per environment and assert the artifact semantically.** Split
config into per-environment files (dev/stage/prod), commit only the `.example`
templates, and make the verify step assert *semantic* health: decode the baked
frontend credential (e.g. JWT issuer/project-ref) and fail unless it belongs to
the target env — not just that assets return 200. A build carrying the wrong
env's key 401s every call while appearing live (200s everywhere).

**Don't source a whole env file into a same-origin web build.** A same-origin web
app should resolve its backend base URL from its own origin, leaving the explicit
override *empty* in production builds; extract only the single value you need
rather than sourcing a whole local `.env` (which leaks a localhost backend URL
into the shipped bundle and breaks every request for real users). Then grep the
built bundle to assert no `localhost` leaked — a wrong-origin bake is data-dead but
looks "up".

**Use unique secrets, fail closed on demo defaults, scan keylessly in CI.** Never
let a tunneled/deployed stack run on a framework's public demo secret — a
world-known signing key lets anyone forge a privileged token (a full
auth/RLS-bypass vuln). Generate unique secrets, fail-closed when any secret equals
a known default, and force-recreate (not restart) services so rotated secrets take
effect, realigning any volume-baked DB password in the same step. Read every
secret from an env var bound at deploy from a secret manager, never a literal or
default arg. Add a secret-scanner as a required check; where native scanning is
paid-gated, run it in Docker (RE2-based scanners like gitleaks reject regex
lookahead — a `(?!)` panics them), allowlist the local `.env`, and drive deploys
from a version-controlled manifest with OIDC/WIF auth.

**Make the version stamper exclude its own outputs.** A git-dirty/version stamper
must exclude its own generated artifacts (VERSION file, `version.json`, deploy
ledgers) from the dirty check, or every build falsely stamps itself `-dirty`
because the stamping step rewrites tracked files.

**Never let an unattended secret source depend on an interactive desktop app.** A
vault CLI that brokers auth through a GUI app (1Password's `op`, and peers) dies
the moment that app is closed or locks — i.e. precisely when the operator has
walked away, which is when unattended runs happen. The failure is also
*misdiagnosable*: `op` reports `No accounts configured for use with 1Password
CLI`, which reads like a missing-integration setup problem and sends you hunting
for a toggle that was enabled all along; the real tell is `op account list`
exiting **0 with empty output**. A locked vault will also *hang* rather than
fail, because the CLI blocks on an unlock prompt it cannot draw from a
non-interactive subprocess — so put a hard timeout on every vault-CLI call in a
test or deploy path. Resolve secrets through a layered chain instead —
**env var → OS keychain → vault CLI, first hit wins** — so CI, unattended local
runs, and interactive runs each have a source that works, and make the failure
message name every source it tried plus the exact command to fix it. On macOS the
login Keychain (`security add-generic-password` / `find-generic-password -w`) is
encrypted at rest, needs no app running, and reads from a subprocess without
prompting. Vendor "service account" tokens are the vendor-blessed answer but
usually require an admin-console sign-in to mint, so they cannot bootstrap
themselves from inside an automated session — check plan *and* role before
promising one.

**Keep secrets out of argv, not just out of shell history.** Prefer the prompting
form of any secret-taking command (e.g. `security add-generic-password -U` with
no `-w`) so the value never becomes a process argument at all. The "prefix the
command with a space" convention is a shell *option* (`HIST_IGNORE_SPACE`), not a
default — recommending it without first verifying it is enabled is exactly how a
password ends up in history anyway. And argv is visible to other local processes
via `ps`, which purging history does not fix. If a purge is needed: delete in
place with **no backup file** (`sed -i.bak` just re-exposes the secret), scan
per-session history files and not only the main one, and remember the live shell
rewrites its history on exit — so the operator must drop `HISTFILE` in that
window, or verify afterwards that the entry did not reappear.

---

## Docker gotchas

**A source-less compose service runs stale baked code.** A Compose service with
no source volume mount runs a *stale* baked image, and on Docker Desktop for macOS
a long-running container caches its bind-mount view — so test/format/lint/serve
targets silently execute old code on a plain `up -d`. Rebuild with
`--build`/`--force-recreate` the serving container, add a source mount when the
command must reflect current files or write results back to the host (in-place
formatters), and verify by grepping a known string out of the actually-served page
(plus container `StartedAt`), not just "Started".

**Regenerate lockfiles under a newer package manager for the full platform
matrix.** Generate/regenerate an npm lockfile under npm ≥ 11 to capture the full
cross-platform `optionalDependencies` set; older npm records only the current
platform's optionals and silently reports "up to date", so `npm ci` fails on other
OS/arch. Guard with a lockcheck step that runs `npm ci --dry-run` in a clean
container and fails loud on "Missing from lock file".

---

## Testing & the harness as "eyes"

**Run a Dockerized browser E2E harness against the real engine.** Run a
Playwright screenshot/walk harness in Docker hitting the app over the internal
Compose network (no tunnel/TLS/interstitial) and *read the shots* — it repeatedly
finds wiring bugs code-reading misses (missing DB grants → 401, reversed default
sort, redirect bugs). For canvas/web UIs, enable the accessibility/semantics tree
and wrap controls with accessible names so they're addressable, add a
demo-data/location override so gated flows populate, assert navigation by
on-screen *content* when the URL doesn't update, and dismiss first-run modals
before asserting. A mobile user-agent in Chromium does *not* reproduce Safari — use
the actual WebKit engine at a real touch viewport, prefer tap over pan-velocity for
critical interactions (swipe fires unreliably on iOS Safari), and remember WebKit
blocks geolocation over insecure HTTP.

**Record a panel/extension UI end-to-end without a live login or backend.** Iframe
the panel's web-accessible resource into a staged host page so page + panel +
cursor are one automated page, seed auth/storage offline to bypass login, stub
network calls via route interception, and capture with the automation framework's
built-in video recorder (Playwright `recordVideo`) rather than OS screen-grab
(`ffmpeg x11grab` gave black frames on a bare virtual display).

**Distinguish synthetic users with a flag, and simulate through the real RPC
path.** Mark test/synthetic users with an explicit boolean column as the source of
truth (not a mutable, user-facing username convention); make analytics and
leaderboards filter by an audience parameter that defaults to "real" and fails safe
on unknown values — exclude, don't delete. Validate funnels/retention/revenue with
a synthetic-user simulator that drives the *real* anonymous RPC path (not raw DB
inserts) using back-dated cohorts, so it exercises the whole stack.

**Run an adversarial bug-hunt only where logic is pure and testable.** An
automated diverse-lens bug-hunt (finders plus majority-refute skeptics,
default-refuted when uncertain) is high-value only where the coupled logic can be
extracted into *pure*, unit-testable helpers: extract, then fix test-first (prove
the old expression was wrong by evaluating it). Wind it down when the hit-rate
decays and only low-testability DOM/glue code remains, and always gate on an
independent full-suite re-run, not the workflow's own verdict.

**Ship a critique harness that gates on its exit code.** Drive a scripted
end-to-end scenario against a running backend and run a deterministic critic over
the transcript; make the process exit code the count of high-severity findings so
CI or a self-paced loop can gate on it (0 high-severity = the bar).

---

## LLM & external-dependency architecture

**Keep a hard determinism boundary around LLM features.** Let the engine/state
machine own canonical truth; the LLM only proposes structured inputs (which
deterministic typed code then validates/scores) or narrates read-only — it never
mutates canonical state. Always ship a deterministic fallback so the product works
with no LLM/key, which also makes the logic unit-testable.

**Route LLM calls through a thin verbatim proxy with per-app metrics.** Forward
multiple apps' LLM calls through a thin local proxy that passes messages verbatim
when a concrete model is named (adding no system prompt or tools) and only invokes
agent tooling on an "auto" model, tagging each request with a client-id header.
You get central per-app call metrics while each app's own prompt stays
authoritative and isolated.

**Put every external dependency behind an interface, a fake, and a config-gate.**
Wrap each external dependency (LLM client, reference/data provider, OTP/SMS
deliverer, OAuth exchanger) in a Protocol/interface with an injectable fake for
tests, and config-gate the feature so it's inert (or falls back) until credentials
are supplied. Tests stay hermetic, the app boots with no third-party keys, and
providers are swappable.

**Make any answer-bearing learning surface answer-safe.** For a surface that must
not reveal an answer before the exercise is done: derive a sanitized presenting
view (never the raw title/label, which may encode the answer), embed a soft prompt
instruction, *and* pass model output through a deterministic redactor that masks
the known answer terms — with a test that runs the guard over every seed case so a
self-revealing case fails CI.

**Align drifted clients with a boundary-DTO contract, not a shared internal
model.** To reconcile two clients of one backend that have drifted into
incompatible shapes, publish a boundary-DTO/contract package that owns only the
payload shape plus a normalizer at the parse/serialize edge — each client keeps its
own internal shape and adapts the DTO at its boundary, adopting incrementally.
That's lower-risk than a shared internal model or a big-bang migration of every
field-access site.

---

## Security

**Treat capability-token inputs as untrusted amounts.** With anonymous
capability-token auth (a bearer UUID), possession proves identity but never
honesty or how-much. Any endpoint that mints points/currency/XP must server-derive
or hard-cap every economically load-bearing input and back it with a DB `CHECK`
constraint — never use the client-generated token as an anti-abuse identity, and
never trust a caller-supplied amount/count/reward.

**Scrub PII deterministically before storage and any LLM call.** Run a
deterministic PII scrubber (SSN/email/phone/ID numbers/dates/ZIP+4/labeled-names)
before persistence and before sending anything to an external LLM, with a policy
switch (reject high-confidence identifiers vs. redact). De-identifying at the
boundary is the cheapest way to stay out of regulatory scope; robust name
detection needs a trained NER, so gate that carefully.

**Defend server-side fetch of user-supplied URLs against SSRF.** Any server-side
fetch of a user-supplied URL needs SSRF defense: restrict to an http/https scheme
allowlist, resolve the host and reject any private/loopback/link-local IP,
re-validate after every redirect, and bound response size and time. Treat
in-process checks as best-effort and add an egress-allowlist proxy for real
production.

**Roll out new authentication in phases to avoid mass lockout.** Ship a stateless
expiring token (e.g. HMAC-SHA256 mint/verify/require), deploy verification in
non-enforcing log-only mode first, and flip to enforce only after telemetry
confirms clients are sending valid tokens and a grace window has passed. Order the
flip by blast radius — mutations (delete/write) before reads.

---

## Product & monetization

**Design bring-your-own-key features deliberately.** Decide up front between
backend-relayed (backend skips its metered quota) and client-direct (key never
leaves the client). Centralize key attachment in one helper, mask the key in the
UI with a reveal toggle, never log it, and don't expose the input until the server
actually honors and never-logs the key.

**Model a paid tier as a payment-agnostic entitlement.** Represent paid features
as an entitlement flag any provider can flip via webhook. On web, a direct payment
processor is the lowest-fee path; adopt a store-unifying subscription SDK only when
native apps exist (to handle mandatory store billing) — it can wrap the web subs,
so it's not either/or.

**Build the internal admin dashboard thin, in-repo.** For a metrics-plus-actions
dashboard, build thin in-repo rather than adopting a heavy BI tool (OSS BI covers
read-only charts but can't safely fire gated write-actions). Make it a static page
holding no privileged key, reads via one aggregate RPC, and any write-action
dispatched to a CI workflow/self-hosted runner (a serverless Worker can't shell out
to long Docker/deploy jobs). Authenticate with org SSO, not a static bearer, and
require a real second factor for production mutations.

---

## Keeping the template alive

**Distil recurring scaffolding into a versioned template with a lift-log.** Turn
recurring project scaffolding into a versioned cookiecutter-style template: token
substitution run in Docker (no host SDKs), whitelist substitution so CI `${{ }}`
expressions aren't clobbered, a universal meta-layer plus per-stack overlays with
known gotchas baked into comments, and a documented "lift-log" process for
harvesting reusable fixes from real projects back into the template.
