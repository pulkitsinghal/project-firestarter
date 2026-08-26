# Integration and rollback

## Safe adoption sequence

1. Enable `include_agent_eval_harness=yes` and run the bundled hermetic
   validation.
2. Produce evaluation cases with a project-owned authoring step. Keep the raw
   agent input local; publish only an opaque `fixtureId` and its `sha256`
   digest into the case, and store the synthetic input values separately.
3. Produce candidate outputs by reducing the agent's real output to
   content-addressed evidence: opaque field tokens, scalar/bounded-list values,
   and a recomputed `sha256` digest per evidence record. Keep raw text local.
4. Call `harness.evaluate(case, candidate, input_fixtures)` in-process. Treat
   `unavailable` as "cannot score yet" (missing input or unverifiable evidence),
   never as a pass.
5. If you record an optional model critique, keep it in `advisoryCritique`. Do
   not build any gate that reads it; the harness deliberately excludes it from
   scoring, and downstream consumers should too.
6. Re-run the privacy scan, the adversarial catalog, and the schema/enum
   lockstep checks in CI whenever you extend the vocabularies.

Steps 2–5 are the integrator's responsibility and are not implemented by this
add-on.

## Rollback

The add-on is default-off and isolated under `tools/agent_eval_harness/`. To
remove it from a generated project, delete that directory and remove any
consumer imports added later. To stop stamping it, omit the include flag or set
it to `no`.

For a Firestarter source rollback, revert the single feature commit or remove:

- the `include_agent_eval_harness` config entry;
- the add-on registration in `bin/generate.py`;
- `addons/agent_eval_harness/`;
- the matching CI contract test and documentation entries.

No database, network resource, model endpoint, service, account, credential,
operating-system setting, or deployment is created, so version 0.1 has no
external cleanup.
