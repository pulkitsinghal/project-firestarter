# Browser automation policy 0.1

This package is a source-only reference contract for deciding whether a typed
browser action proposal may be handed to a separately approved future
executor. It does not observe or control a real browser.

## Trust and data flow

```text
trusted user task / local voice
             |
             v
bounded intent normalization (no selector or execution authority)
             |
             v
capability grant + typed action proposal
             |
             v
semantic DOM observer contract ----> Relative XY fallback
             |                         (only after identity; bounded geometry)
             +---------------------> Citrix/remote adapter
                                       (separate session/control surface)
             |
             v
policy + confirmation + ledger
             |
             v
content-free future-executor handoff
             |
             X  no executor is shipped
```

Page content is untrusted data. It may produce finite observation state or a
prompt-injection signal ID, but it cannot change the task, grant, allowlists,
action, destination, confirmation, fallback, or executor.

Browser-local observers must replace raw details before crossing this contract:

- origins become product-owned `originId` values;
- accessible names become allowlisted semantic tokens;
- payloads become digests plus a finite effect class;
- page instructions become bounded signal IDs;
- evidence includes only IDs, generations, enums, counts, and reason codes.

Raw page text, URLs, paths, query strings, selectors, form values, cookies,
browser storage, credentials, screenshots, OCR, and private records are not
fields in the contract.

## Adapters

1. `semantic-dom` is authoritative. It requires an exact role, accessible-name
   token, container contract, strict uniqueness, current document/frame
   binding, visibility, enabled state, stability, and unobscured hit evidence.
2. `relative-xy` is a bounded fallback only when semantics are explicitly
   unavailable for one already identified app-owned contract. Ambiguity,
   closed shadow roots, cross-origin blockage, stale state, hidden elements,
   overlays, missing training, or generation drift cannot fall back.
3. `citrix-remote` is a separate adapter with local-window,
   remote-session/control-epoch, frame-freshness, focus, trained-region, and
   transform-generation checks. Remote pixels never become DOM semantics.
4. `voice-intent` maps trusted local speech into a product-owned intent/effect
   catalog. It never emits a node, selector, coordinate, grant, confirmation,
   or executor command.

## Ledger and handoff

The reference ledger is in memory and has no effects. It models
`planned -> confirmed -> handed-off -> succeeded|failed|indeterminate`.
Same-key/same-digest replay refuses deterministically; same-key/different-digest
is an idempotency collision; an indeterminate prior effect can never retry
automatically.

`allowed: true` means only that a short-lived, digest- and lifecycle-bound
handoff was authorized. Every emitted handoff states `executorConfigured:
false`. Integrators must add durable storage, independent executor
authentication, postcondition reconciliation, and a new explicit execution
gate before any real effect.

## Validation

The package uses only the Python standard library and synthetic fixtures:

```bash
PYTHONPATH=. python3 -B -m tools.browser_automation_policy.run_validation
```

See `docs/POLICY_CONTRACT.md` for invariants and
`docs/INTEGRATION_AND_ROLLBACK.md` for adoption and removal.
