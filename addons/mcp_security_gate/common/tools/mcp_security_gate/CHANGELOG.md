# Changelog

## [0.1.0] - 2026-08-26

### Added

- Source-only, offline MCP-server security gate over a declared risk manifest.
- Closed contract vocabulary: check ids, verdicts (pass/fail/not-applicable),
  a disposition (allow/block), stable reason codes, and effect/reversibility/
  posture/token/degraded enums.
- Content-minimized `ToolManifest` and `RiskManifest` dataclasses with strict
  `to/from_contract_dict`, opaque-ID and `sha256:<64hex>` validation, and no
  endpoints, credentials, tokens, or payloads.
- Ten deterministic static risk checks: effect soundness, confirmation for
  irreversible/destructive effects, untrusted-annotation handling, token
  audience/passthrough (confused-deputy avoidance), output sanitization,
  secret/log leakage, timeouts, rate limits, response size caps, and
  degraded-state fail-closed behavior.
- Fail-closed evaluator: any missing, unknown, or degraded posture yields a
  fail and blocks the whole server; allow only on all-applicable-pass.
- Closed JSON Schema 2020-12 risk-manifest and gate-report documents, enum-
  locked to the contract module.
- Synthetic fake-MCP-server fixtures: a clean-pass set and an adversarial set
  covering every failure mode, each mapped to an executable test via a coverage
  map.
- Hermetic `run_validation` verifying schema/enum lockstep, fixture and coverage
  integrity, and a static privacy/capability scan, then running the suites.
