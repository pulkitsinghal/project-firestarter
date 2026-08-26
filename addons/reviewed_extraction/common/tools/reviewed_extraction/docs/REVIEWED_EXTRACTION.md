# Reviewed extraction contract

## Scope

Version 0.1 is a hermetic reference contract, not an extraction pipeline. It
accepts typed, content-minimized synthetic claims about opaque field paths and
folds human review decisions into an allowlisted egress payload. No model, OCR
path, document store, network client, credential flow, or deployment is
included. The reducer and egress builder are pure standard-library code.

Requirements were derived independently from Firestarter/Auggie review needs
and neutral public standards: W3C PROV (each released field carries source and
actor provenance), JSON Schema 2020-12 (closed, enum-locked contracts), and the
data-minimization and purpose-limitation principles common to general privacy
guidance. No third-party extraction gallery was cloned, inspected, or adapted.

## Data separation

Raw source documents stay caller-side and private. A claim references its source
only by:

- an opaque `sourceId`;
- a `sha256:` `sourceDigest` of the whole source;
- integer `startOffset` / `endOffset` character positions.

The extracted `value` a reviewer confirmed is a bounded opaque token. The raw
span the value came from is never copied into a claim, a reduced decision, an
evidence result, or an egress payload. `verify_evidence(source_bytes, claim)`
checks the digest and offset range against caller-held bytes and returns only a
typed code plus the source ID and digest.

## Closed review-state vocabulary

`proposed`, `confirmed`, `corrected`, `unknown`, `omitted`, `conflicted`,
`superseded`. Any other string is rejected at the contract boundary.

## Reducer precedence

Applied per field path, in order:

1. Supersession removes claims. A claim is inactive if its own state is
   `superseded` or if its `claimId` appears in another claim's `supersedes`.
2. An explicit `conflicted` state on any active claim withholds the field.
3. Among active releasable claims, `corrected` outranks `confirmed`. The winner
   is the highest-precedence claim, ties broken by higher `sequence` then
   `claimId`.
4. Two or more active releasable claims at the top tier with different values
   withhold the field as `withheld-conflicted`.
5. With no releasable claim, the withheld reason is `proposed` > `unknown` >
   `omitted`; with no active claim, `withheld-superseded`.

## Allowlisted egress

`build_egress(requested_field_paths, reductions, purpose=, recipient_id=)`
emits a field only when every gate passes: the path was requested, a decision
exists, the decision is `confirmed`/`corrected`, and its purpose and recipient
match the request (purpose limitation). Non-requested paths are never iterated,
so a releasable-but-unrequested field cannot leak. Every drop is recorded with a
typed reason code. The released value is copied from the human decision; the
model never authors the payload.

## Validation

```bash
PYTHONPATH=. python3 -B -m tools.reviewed_extraction.run_validation
```

See `INTEGRATION_AND_ROLLBACK.md` for adoption and removal.
