# Integration and rollback

## Safe adoption sequence

1. Enable `include_browser_automation_policy=yes` and run the bundled hermetic
   validation.
2. Implement a browser-local observer that outputs the closed semantic
   observation schema. Keep raw DOM/page data local and ephemeral.
3. Add shared durable ledger persistence and prove atomic nonce/idempotency
   consumption plus crash/restart replay behavior.
4. Add a user-owned confirmation surface that binds exact proposal digests and
   lifecycle generations.
5. Design an executor as a separately reviewed component. Authenticate and
   atomically consume one unexpired handoff nonce and idempotency key once,
   re-check grant expiry, lifecycle, and actionability, reconcile the declared
   postcondition, and preserve `indeterminate` on uncertainty.
6. Repeat the privacy, adversarial, and exact-default tests before considering
   any real-surface pilot.

Steps 2–6 are not implemented or authorized by this add-on.

## Rollback

The add-on is default-off and isolated under `tools/browser_automation_policy/`.
To remove it from a generated project, delete that directory and remove any
consumer imports added later. To stop stamping it, omit the include flag or set
it to `no`.

For a Firestarter source rollback, revert the single feature commit or remove:

- the `include_browser_automation_policy` config entry;
- the add-on registration in `bin/generate.py`;
- `addons/browser_automation_policy/`;
- the matching CI contract test and documentation entries.

No database, browser permission, profile, extension, operating-system setting,
service, account, network resource, or deployment is created, so version 0.1
has no external cleanup.
