# Permit verifier migration and rollback

## Upgrade from 0.1.0

Version 0.2.0 is additive. The 0.1 synthetic catalog, planner, lifecycle API,
status, and telemetry remain unchanged. Existing generated projects do not
create a permit ledger unless an integrating process explicitly constructs
`PermitVerifier`.

Before using the new API:

1. Verify the exact merged local-ai ref and every hash in
   `local-ai-contract-pin.json` against the byte-identical compatibility
   fixtures.
2. Re-run the copied producer fixtures through Firestarter's runtime validator
   and confirm byte-for-byte digest parity.
3. Supply the expected producer-schema and catalog digests plus exact executor
   and state generations to the verifier constructor. Also supply the exact
   catalog-derived plan digest for each allowed service/intent pair; an
   otherwise valid reordered or policy-mutated plan must not enter that map.
4. Supply a trusted PM keyring plus a distinct handoff-receipt signing key in
   memory. Pin the verifier instance, verifier-artifact digest, contract-pin
   digest, receipt key ID, and bounded receipt lifetime. Do not commit a key or
   introduce an environment-variable convention in this add-on.
5. Place the ledger in a private local state directory. The verifier creates
   the file mode `0600` and refuses symlinks/non-regular files.
6. Treat only the separately signed handoff receipt as broker input. The broker
   must verify every scope/provenance field and atomically consume the receipt
   nonce in its own durable ledger. No executor or broker is supplied by this
   release.

New PM permit ledgers use SQLite `user_version=2`. Opening a version 1 ledger
atomically preserves its consumed nonce fingerprints and revocations while
removing the obsolete generation-wide uniqueness constraint; legacy rows have
no recoverable permit ID, so their nonce replay protection remains the durable
authority. Unknown future versions fail closed. There is no automatic
downgrade or lossy migration.

## Rollback

Code rollback is source-only:

1. Stop the not-yet-integrated handoff consumer, if one exists.
2. Revoke any outstanding permit nonces at the PM authority.
3. Regenerate without `include_service_supervisor`, or revert the 0.2 source
   while retaining the ledger as audit evidence.
4. Return to the unchanged 0.1 synthetic-only lifecycle surface.

Do not delete or edit the ledger as part of ordinary rollback. Keeping it
prevents old signed permits from becoming reusable after a code rollback. If a
ledger must be retired, first revoke/expire every associated permit and archive
the mode-`0600` file through an owner-approved retention path; deletion is a
separate destructive action.

No service rollback command follows from this document. Apply rollback is a
separate signed authorization phase with a different PM nonce and a distinct
signed handoff receipt/receipt nonce. A failed rollback result remains failed
and requires review; it never authorizes retry, cleanup, or a host mutation.

## Refusal recovery

- `PLAN_DIGEST_MISMATCH`: regenerate the plan; never patch its digest.
- `WRONG_PERMIT_SCOPE` or `WRONG_AUTHORITY_GENERATION`: obtain a new permit for
  the exact current plan/context.
- `STALE_PERMIT`, `REPLAYED_PERMIT`, or `REVOKED_PERMIT`: never reuse the
  permit; issue a fresh nonce after re-evaluating policy.
- `STATE_*`: preserve the state file, stop handoff, and recover from a verified
  backup or audited snapshot. Never replace a corrupt ledger with an empty one
  while old permits remain live.
- rollback failure: keep the service state unknown, revoke remaining permits,
  and require a separate scoped recovery plan and permit.
