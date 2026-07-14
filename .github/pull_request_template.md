<!--
Firestarter changes affect the generator and/or every project it stamps. Keep
the evidence concrete. See AGENTS.md and template/docs/FEATURE_HANDOFF.md.
-->

## Summary
<!-- 1–3 sentences, including the intended conventional-commit subject. -->

## Why
<!-- What reusable problem this solves and why it belongs in Firestarter. -->

## Generated-project impact
<!-- Which template/stack/add-on paths change? What does a newly stamped project receive? -->

## Test plan
<!-- List exact Dockerized stamp checks and any generated-stack tests. -->

## Feature handoff evidence
<!--
Record the acceptance path, meaningful failure/retry/rollback/cleanup path, and
exact checks. For visible work, link real rebuilt-app storyboard frames and a
Mermaid state/flow map. Link a short captioned release cut for a material
multi-step flow only when the generated project ships a reproducible harness;
otherwise mark video N/A and provide a still walkthrough. For non-visual work,
write N/A with a reason and link equivalent generated-file/request/log/build or
state evidence. Use synthetic/test data in every artifact.
-->

## Checklist

- [ ] Every declared stack example stamps cleanly in Docker
- [ ] No unintended `{{ token }}` leaks; GitHub/JS brace syntax is preserved
- [ ] `docs/ANATOMY.md` and `docs/LIFT-LOG.md` updated for a lifted precept/component
- [ ] Conventional-commit subject (`type(scope): subject`, ≤100 chars)
- [ ] Acceptance, failure/recovery, rollback, and exact verification evidence is attached (N/A explained)
- [ ] UI changes refresh the real-app storyboard and state map, or N/A is explained
- [ ] Material multi-step UI work links the supported release cut, or video N/A is explained
