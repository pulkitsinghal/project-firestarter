# Integration and rollback

## Safe adoption sequence

1. Enable `include_reviewed_extraction=yes` and run the bundled hermetic
   validation.
2. Implement an extractor that emits claims in the closed extraction-claim
   schema. Keep raw source documents local and private; reference them only by
   opaque source ID, `sha256:` digest, and character offsets.
3. Add a reviewer surface that lets a person set each claim's state to
   `confirmed`, `corrected`, `unknown`, `omitted`, or `conflicted`, and records
   the opaque actor ID, purpose, and recipient.
4. Fold reviewed claims with `reduce_claims`, verify each releasable claim's
   evidence with `verify_evidence` against the caller-held source bytes, and
   build outbound payloads only with `build_egress` for an explicit requested
   field set, purpose, and recipient.
5. Persist raw source bytes and reviewer identity in your own audited store, not
   in claims or egress payloads. Re-run the privacy, adversarial, and exact
   default tests before any pilot.

Steps 2–5 are not implemented or authorized by this add-on.

## Rollback

The add-on is default-off and isolated under `tools/reviewed_extraction/`. To
remove it from a generated project, delete that directory and any consumer
imports added later. To stop stamping it, omit the include flag or set it to
`no`.

For a Firestarter source rollback, revert the single feature commit or remove:

- the `include_reviewed_extraction` config entry;
- the add-on registration in `bin/generate.py`;
- `addons/reviewed_extraction/`;
- the matching CI contract test and documentation entries.

No database, network resource, credential, model, or deployment is created, so
version 0.1 has no external cleanup.
