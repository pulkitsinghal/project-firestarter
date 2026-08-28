# Reviewed extraction 0.1

This package is a source-only reference contract for turning human-reviewed
structured-extraction claims into an allowlisted outbound payload. It does not
read documents, run a model, or send anything.

## Trust and data flow

```text
private source document (caller-held bytes)
             |
             v
extractor proposes claims (opaque field path + value token + evidence ref)
             |
             v
human review sets a closed state + actor + purpose + recipient
             |
             v
deterministic reducer  (supersession, conflict, correction precedence)
             |
             v
allowlisted egress builder  (confirmed/corrected  ∩  requested  ∩  purpose)
             |
             v
content-minimized egress payload  (reviewer values + provenance only)
```

A claim never carries raw source content. It references its source by an opaque
`sourceId`, a `sha256:` `sourceDigest`, and integer character offsets. The
`value` is the structured token a reviewer confirmed, not the raw span.

## Reducer

`reduce_claims` folds all claims for one opaque field path into a single
`ReducedDecision`. `corrected` overrides `confirmed`; superseded claims drop
out; disagreeing releasable values or an explicit `conflicted` state withhold
the field. The fold is pure code and stable across runs.

## Egress

`build_egress` releases a field only when it was explicitly requested, has a
`confirmed`/`corrected` decision, and matches the request's purpose and
recipient. Non-requested paths are never iterated, so nothing off the allowlist
can leak. Every dropped field is recorded with a typed reason code. The model
never authors the payload: values are copied from human decisions.

## Evidence

`verify_evidence(source_bytes, claim)` checks the claim's source digest and
offset range against the caller's private bytes and returns a typed
`EvidenceResult` with only the code, source ID, and digest. Raw bytes stay with
the caller.

## Validation

```bash
PYTHONPATH=. python3 -B -m tools.reviewed_extraction.run_validation
```

See `docs/REVIEWED_EXTRACTION.md` for invariants and
`docs/INTEGRATION_AND_ROLLBACK.md` for adoption and removal.
