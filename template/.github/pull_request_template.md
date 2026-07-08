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

## Checklist
- [ ] `make precommit` passes locally (all gates, in Docker)
- [ ] Conventional-commit subject (`type(scope): subject`, ≤100 chars)
- [ ] Migrations are forward-only and idempotent (or N/A)
- [ ] Docs updated (`ARCHITECTURE.md` / `PROJECT_STATUS_AND_NEXT_STEPS.md`) if behaviour changed
