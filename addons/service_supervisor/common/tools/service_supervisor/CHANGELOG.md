# Changelog

## Unreleased

- Fixed repeat acquisition for independently signed permit IDs/nonces targeting
  the same deterministic plan and authority generation. State schema 2 retains
  atomic nonce replay protection, durably binds each permit ID to one exact
  signed payload, and migrates schema 1 ledgers without losing prior
  consumption or revocations.

## 0.2.0 - 2026-07-28

- Added strict typed validation for the local-ai adapter plan/result v1 seam,
  including deterministic plan hashing, discriminated launchd/Compose/Ollama
  operations, fixed argv/loopback HTTP shapes, readiness, and typed rollback.
- Added signed PM execution permits bound to the exact plan digest, service,
  intent, apply-versus-rollback phase, operation set, adapter set, producer
  schema, catalog, executor generation, state generation, issue/expiry window,
  nonce, key, and policy version.
- Added a mode-`0600` SQLite nonce/revocation ledger with atomic one-use
  consumption, restart persistence, concurrency safety, deterministic bounded
  snapshots, corrupt/symlink refusal, and transaction rollback on interruption.
- Added content-free permit telemetry and adversarial coverage for absent,
  stale, replayed, revoked, conflicting, wrong-scope, wrong-generation, and
  tampered permits; injection, digest, ordering, result, readiness, rollback,
  corruption, and race failures also fail closed.
- Kept the runtime source-only and non-executing. Authorization returns only
  `AUTHORIZED_FOR_EXECUTOR_HANDOFF`; this package still contains no executor,
  listener, subprocess, shell, Docker socket, network client, launchd action,
  Docker action, or Ollama action.
- Pinned local-ai lifecycle v1 at merged main
  `3986befb06106b66795444d54f8513ead83f76b0`, including exact schema,
  catalog, observations, plan, result, unsigned-permit fixture hashes, and
  byte-identical compatibility fixtures.
- Replaced the unauthenticated decision seam with a separately signed,
  short-lived, one-use broker handoff receipt bound to verifier/pin provenance,
  exact plan scope, generations, permit identity, and a distinct receipt
  nonce. Receipt replay consumption belongs to the future broker; no broker or
  executor ships here.

## 0.1.0 - 2026-07-28

- Added a strict versioned service catalog, matching machine-readable JSON
  Schema, and deterministic wake/sleep planner.
- Added the `STOPPED` / `STARTING` / `READY` / `DRAINING` / `FAILED` lifecycle.
- Added concurrent first-request coalescing, dependency-DAG wake ordering,
  bounded readiness, leases, idle drain/grace, retain and never-stop pins.
- Added synthetic-only lifecycle cleanup, dependency rollback, and privacy-safe
  bounded transition telemetry.
- Added truthful unavailable resource metrics and fail-closed validation.
- Added a synthetic test-only GET/HEAD wake-before-forward fixture.
- Added the fail-closed, unknown-preserving mapping for local-ai's observe-only
  inventory contract; it grants no management permission.
- Deliberately omitted Docker, Docker-socket, launchd, Ollama, subprocess,
  listeners, deployable proxying, install, and real host-service adapters.
