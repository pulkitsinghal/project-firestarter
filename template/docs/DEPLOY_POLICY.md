# Deploy policy — when a deploy is self-authorized

This is the **decision frame**, not the mechanics. The mechanics live in
[`DEPLOY.md`](../DEPLOY.md) / the `deploy` make target and
[`GO_LIVE.md`](GO_LIVE.md); this doc answers the human question those don't:
*when may a change ship without a separate owner sign-off?* Edit the specifics to
match {{ project_name }} — the three-condition shape is the reusable part.

**Default stance:** a deploy does **not** require a separate approval each time.
The gate is the *process below*, not a manual sign-off — if all three conditions
hold, the deploy stands and **no rollback is expected**. A well-tested change
ships without waiting on the owner.

## Self-authorized when ALL THREE hold

1. **Ample testing.** The change is on `master`, green on CI (Tests / Lint &
   Typecheck / Build), and its risky parts were exercised directly — e.g. a DB
   migration was applied to a live database and its behaviour verified (see
   [`migration-rollback.md`](migration-rollback.md)), and the build's own guards
   pass (no default/guessable secret baked in, no `localhost` leak — see
   [`../SECURITY.md`](../SECURITY.md)).
2. **Snapshot verification.** A **before/after snapshot** of the user-facing
   change was produced and reviewed (what exists → what ships), so the visible
   effect is known in advance rather than discovered live. This is the
   storyboard precept applied to a deploy — see [`STORYBOARD.md`](STORYBOARD.md).
3. **Post-deploy sanity check.** Immediately after publishing, a live check
   confirms the change landed and nothing obvious regressed: the deployed build
   reports the new commit, and the specific feature is spot-checked on the live
   URL.

When 1–3 hold, the deploy is complete — rollback is **not** a precondition, and
none is expected. If the post-deploy check *fails*, redeploy the previous good
commit.

## Still human-gated, regardless of the above

The policy loosens *approval*, not these hard lines:

- **Credentials.** No agent enters or supplies a secret — API tokens, cloud
  keys, SMTP creds. An agent may only *run* a deploy when the environment
  **already holds them**, placed by the owner. Supplying a credential is always
  the owner's action (see [`ci-secrets.md`](ci-secrets.md)).
- **Production-DB migrations.** Applying a schema/data migration to the
  production database is **not** an app deploy; it keeps its own review + a
  rollback plan ([`migration-rollback.md`](migration-rollback.md)) and is not
  covered by this policy.
- **Account / billing.** Creating or changing hosting / payment / app-store
  accounts, plans, DNS, or billing stays owner-only.

## Mechanism (reference)

Fill in {{ project_name }}'s actual command and target here (e.g. `make deploy`
→ the tunnel/host it publishes to, and which environment file holds the creds).
Keep it to one paragraph — the *policy* above is the part that travels between
projects; the *mechanism* is stack-specific.
