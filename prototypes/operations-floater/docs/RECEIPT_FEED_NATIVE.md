# Native receipt-feed contract

Operations Floater consumes the dashboard lane's sanitized receipt-feed 1.1
projection as local, read-only input. The reviewed handoff came from dashboard
candidate commit `0e340073708684d8530f0769780e705d9e8c5990`.

## Cryptographic pins

- reviewed current snapshot:
  `e0c598cdcc29ba39f509ccdb553f8d2c65709896827229e3aff1ada07c1bd1f2`
- reviewed LKG snapshot:
  `ae4948b1c6396caca73a372a90474626d82d94291f36cb8bbc973799c6bebea8`
- receipt-feed 1.1 schema:
  `26cfc2cddac67831c6470f32dd54537762be95138661850d70e49a734db3ccc4`
- current-task manifest schema:
  `6b2649aef97774a00ed8323f91ce84c951220243ed4fd8b6d036b715d17a581f`
- reviewed manifest file:
  `a94a8331b303189a99334b8c2f5940418a510326ceabbc1e58c34ee2460af1f8`
- canonical manifest state:
  `0a815cbd060d698b39badc715c16933436b7abec6588ca226bd1ffee4d73cc6a`

The app also carries these pins in source and verifies content-addressed
snapshot bytes against their pointer at every read. Runtime snapshots need not
equal the reviewed fixture hash, but they must satisfy the pinned schema
contract, exact provenance allowlists, and their own pointer digest.

## Selection and freshness

The app reads `receipt-feed-current.json` first. It uses
`receipt-feed-lkg.json` only if the current pointer, digest, JSON, schema, or
provenance is invalid. A valid stale current snapshot stays selected.

Freshness is recomputed at read time as
`max(0, ceil(readAt - generatedAt))`. It is stale only when that conservative
integer age is greater than `thresholdSeconds`; therefore an actual age of
60.9 seconds is 61 seconds and stale at a 60-second threshold.

Missing, invalid, or unavailable sources make only the receipt panel offline.
The existing local snapshot, Router chat and review, voice/floor controls,
race/resource/privacy panels, keyboard behavior, and
window lifecycle remain independent.

## Privacy and mutation boundary

Only the dashboard contract's bounded public labels and status projections are
rendered. The consumer rejects duplicate JSON keys, unknown object fields,
symlinks, oversized input, mismatched hashes, and non-allowlisted provenance.
It never displays raw prompts, source paths, manifest internals, or arbitrary
unknown content. It has no write, network, task-action, or control-plane path.

## Rollback

Revert the focused receipt-view commit and regenerate the Xcode project from
`project.yml`. Removing the local `OperationsFloater/receipts` directory is
optional: old builds do not read it. No Router, service, configuration,
permission, signing, installation, or task state needs to be changed.
