# Agent eval harness contract

## Scope

Version 0.1 is a hermetic reference harness, not an agent runner. It accepts a
typed, content-minimized evaluation case and a candidate output and returns a
deterministic verdict. No model call, network client, subprocess, dynamic
validator import, credential flow, or deployment is included. Requirements were
derived independently from Firestarter/Auggie evaluation needs and neutral
public standards (JSON Schema 2020-12; general test-harness and measurement
conventions such as separating a blocking pass/fail decision from advisory
signals). No third-party evaluation project was consulted, cloned, or adapted.

## Objects

- **Input fixture**: synthetic deterministic input, referenced from a case by an
  opaque `fixtureId` and a `sha256:` digest. Its content is stored separately
  and passed to the reducer as a `{fixtureId: values}` map.
- **Case** (`eval-case-1.0`): opaque `caseId`, a `schemaVersion` tag, an
  `inputFixtureRef` (opaque id + digest), and 1..64 checks. Each check declares
  `checkId`, `kind`, `blocking`, an `evidenceId`, a `fieldToken`, and
  kind-specific `params`.
- **Candidate** (`eval-candidate-1.0`): the output under evaluation as a set of
  content-addressed `evidence` records (`evidenceId`, `digest`, `values`), plus
  an optional `advisoryCritique`.
- **Result** (`eval-result-1.0`): `caseId`, terminal `state`, per-check
  outcomes, `evidenceVerified`, `advisoryCritiqueRecorded`, and a content
  addressed `resultDigest`.

## Closed vocabularies

| Vocabulary | Members |
| --- | --- |
| Check kind | `exact-equals`, `subset`, `regex-match`, `numeric-threshold`, `ordered-contains` |
| Check outcome | `satisfied`, `violated`, `unavailable` |
| Result state | `passed`, `failed`, `needs_review`, `unavailable` |
| Numeric comparator | `ge`, `le`, `gt`, `lt`, `eq` |
| Critique verdict (advisory) | `pass`, `fail`, `inconclusive` |

The JSON schema enums are verified in lockstep with the Python enums by
`run_validation.py`; drift fails the build.

## Checks

Each check reads exactly one observed value: `evidence[evidenceId].values[fieldToken]`.

- `exact-equals`: observed equals the expected scalar or list.
- `subset`: expected list is a subset of the observed list.
- `regex-match`: observed string fully matches the compiled pattern.
- `numeric-threshold`: observed number satisfies `comparator` against `bound`.
- `ordered-contains`: expected list is an ordered subsequence of the observed list.

Checks are pure functions of `(observed, params)`. A present value of the wrong
shape for a check is `violated` (a real malformed answer), never an exception. A
value that is absent, or whose evidence digest does not verify, is `unavailable`.

## Reduction

1. If the referenced input fixture is absent or its digest does not verify, the
   result is `unavailable` (a required input is missing).
2. Otherwise, for each check compute an outcome, then reduce:
   - any **blocking** outcome `unavailable` -> `unavailable`;
   - else any **blocking** outcome `violated` -> `failed`;
   - else any **non-blocking** signal (`violated` or `unavailable`) -> `needs_review`;
   - else -> `passed`.

Blocking checks alone decide `passed`/`failed`. The reducer never runs the
candidate; it only compares reduced values it was handed.

## The advisory critique is never authoritative

A candidate may carry an `advisoryCritique { critiqueId, verdict, noteToken }`.
The reducer records only whether it was present (`advisoryCritiqueRecorded`).

The scoring function `harness._score` takes a single argument, the tuple of
computed `CheckResult`s. It has no parameter through which a critique could
arrive. `harness.evaluate` fixes the verdict by calling `_score` (or the
input-missing branch) **before** it reads `candidate.critique`, and it reads the
critique only to set a boolean. There is therefore no code path by which a
critique's `verdict` or `noteToken` can change `state`. The adversarial test
`test_advisory_critique_cannot_flip_verdict` asserts that every critique verdict
(including `pass`) leaves a failing case `failed`, and that removing the critique
leaves the verdict unchanged.

## Determinism and content minimization

Digests are `sha256` over the canonical JSON of the addressed object
(`json.dumps(..., sort_keys=True, separators=(",", ":"))`). Evaluating the same
inputs twice yields byte-identical results and result digests. Boundary values
are scalars or bounded lists of scalars keyed by opaque tokens; raw prompts,
responses, transcripts, hosts, paths, and credentials are not fields in any
contract, and the privacy scan rejects fixtures that reintroduce them.

## Fail-closed surface

- Unknown root or nested fields on any contract object are rejected.
- Unknown check kinds and unknown numeric comparators are rejected at parse time.
- Tampered or mismatched evidence digests degrade the affected checks to
  `unavailable` (never a silent pass).
- A candidate whose `caseId` disagrees with the case is rejected.
