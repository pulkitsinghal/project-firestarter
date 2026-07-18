<!--
Fill this out. PRs that skip sections may be sent back. See AGENTS.md and
CONTRIBUTING.md for the full workflow. Label the PR `auto-merge` to squash-merge
once checks are green and the AI verdict isn't BLOCKING.
-->

## Summary
<!-- 1–3 sentences. The conventional-commit subject of the squash commit goes
here too: <type>(<scope>): <what>. -->

## Why
<!-- The problem this solves. Alternatives considered and why this approach.
Link any plans, issues, or design docs. -->

## Migration impact
<!--
- Does this add a migration? Which file, what does it do, is it idempotent?
- Forward-only data changes? Backfill steps? Rollback plan if reverted.
- "N/A" only if there are zero schema or data implications.
-->

## Test plan
<!--
- Commands you ran locally (e.g. `make precommit`, `make test`).
- What you verified by hand, if anything (UI, OS-specific steps).
-->

## Feature handoff evidence
<!--
Record the acceptance path, meaningful failure/retry/rollback/cleanup path, and
exact checks. For a visible change, link real-app storyboard frames and the
Mermaid state/flow map. Link the full E2E/release-rehearsal evidence when the
repository provides it. Link a 20–40 second narrated/captioned release cut with
natural voice, subtitles, and focus effects for a material multi-step flow only
when this repository ships a reproducible harness;
otherwise mark video N/A and provide a still walkthrough. For non-visual work,
write N/A with a reason and link equivalent API/log/migration/build/state
evidence. Use synthetic/test data. See docs/FEATURE_HANDOFF.md.
-->

## Checklist
- [ ] `make precommit` passes locally (all gates, in Docker)
- [ ] Conventional-commit subject (`type(scope): subject`, ≤100 chars)
- [ ] Migrations are forward-only and idempotent (or N/A)
- [ ] Docs updated (`ARCHITECTURE.md` / `PROJECT_STATUS_AND_NEXT_STEPS.md`) if behaviour changed
- [ ] Acceptance, failure/recovery, rollback, and exact verification evidence is attached (N/A explained)
- [ ] UI changes refresh the real-app storyboard and state map, or N/A is explained
- [ ] The repository's full end-user E2E/release rehearsal passes, or N/A is explained
- [ ] Narrated E2E evidence is post-processed from normal-speed assertions, without `slowMo` or fixed presentation waits, or N/A is explained
- [ ] Material multi-step UI work links the supported release cut, or video N/A is explained
- [ ] Compact polished media is committed under `docs/media/`; raw recordings remain artifacts, or N/A is explained
