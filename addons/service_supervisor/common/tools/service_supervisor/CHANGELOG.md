# Changelog

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
