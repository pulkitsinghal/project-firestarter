# Changelog

## [0.1.0] - 2026-08-26

### Added

- Source-only, closed architecture manifest contract: components, data stores,
  dependencies, trust boundaries, owner roles, and repo-relative evidence links.
- Deterministic, fail-closed manifest loader/validator with a closed
  `ManifestErrorCode` vocabulary (unknown/missing field, invalid id/enum/digest,
  duplicate id, unresolved reference, derivation cycle, absolute path, identity
  leak, missing evidence).
- Order-independent canonical projection and SHA-256 digest.
- Deterministic Mermaid `flowchart TD` and ANATOMY-style Markdown table
  renderers (pure functions, stable ordering, no timestamps or randomness).
- Normalized-content drift check binding a rendered artifact to the manifest,
  fail-closed on malformed input or unknown artifact kind.
- Closed JSON Schema 2020-12 contracts for the manifest, the drift report, and
  the render envelope, kept in lockstep with the Python enums.
- Hermetic synthetic fixtures: a golden manifest and an adversarial corpus that
  maps every scenario to an executable, fail-closed test method.
- Static privacy scan of the package source and every emitted artifact.
