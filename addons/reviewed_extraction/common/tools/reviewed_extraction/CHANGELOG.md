# Changelog

## [0.1.0] - 2026-08-26

### Added

- Versioned, content-minimized extraction-claim contract with a closed review
  state set (`proposed`, `confirmed`, `corrected`, `unknown`, `omitted`,
  `conflicted`, `superseded`), opaque actor, purpose-limitation metadata, and
  digest-plus-offset evidence references that never inline raw source content.
- Deterministic reducer that folds a claim set into one decision per field
  path with documented supersession, conflict, and correction precedence.
- Allowlisted egress builder that releases only fields that were explicitly
  confirmed or corrected AND requested AND purpose/recipient matched; every
  other field is dropped fail-closed with a typed reason code.
- Evidence verification (`verify_evidence`) that checks source digest and
  offset range against caller-held bytes without persisting raw content.
- Closed JSON Schema 2020-12 contracts (claim, reduced decision, egress
  request, egress payload, evidence result) kept in enum lockstep with the code.
- Hermetic synthetic fixtures and an adversarial coverage matrix mapping every
  scenario to an executable deterministic test.
