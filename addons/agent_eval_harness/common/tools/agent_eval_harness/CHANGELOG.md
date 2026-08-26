# Changelog

## [0.1.0] - 2026-08-26

### Added

- Source-only, deterministic agent-evaluation harness with a closed check
  vocabulary and a closed result-state vocabulary.
- Versioned eval-case, eval-candidate, and eval-result JSON schemas (draft
  2020-12, `additionalProperties: false`), enum-locked to the Python contracts.
- Pure, stdlib-only blocking checks: exact-equals, subset, regex-match,
  numeric-threshold, ordered-contains.
- A deterministic reducer that verifies content-addressed evidence digests,
  computes every declared check, and reduces blocking checks to
  `passed | failed | needs_review | unavailable`.
- Structural quarantine of the optional model critique: it is a recorded
  advisory annotation that is never in scope for the scoring function.
- Fail-closed parsing of unknown fields, unknown check kinds, unknown
  comparators, malformed cases/candidates, and tampered digests.
- Hermetic synthetic fixtures (scoring vectors plus an adversarial catalog) with
  a coverage map to executable tests, and a static privacy scan.
