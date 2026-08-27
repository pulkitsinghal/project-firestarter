# Deploy policy — when a deploy is self-authorized

This is the **decision frame**, not the mechanics. The mechanics live in
`DEPLOY.md` when the selected stack supplies it, the `deploy` make target, and
[`GO_LIVE.md`](GO_LIVE.md); this doc answers the human question those don't:
*when may a change ship without a separate owner sign-off?* Edit the specifics to
match {{ project_name }} — the three-condition shape is the reusable part.

**Default stance:** a deploy does **not** require a separate approval each time.
The gate is the *process below*, not a manual sign-off — if all three conditions
hold, the deploy stands and **no rollback is expected**. A well-tested change
ships without waiting on the owner.

Execution safety is a separate boundary from deploy authorization. A deploy may
keep the self-authorized path only when it satisfies this policy, is cost-neutral
and mechanically reversible, its audience/content class is already authorized,
and it is not a first disclosure of private, regulated, or competitively
sensitive material. "Mechanically reversible" requires an exact immutable prior
artifact plus evidence that it still works with the current schema,
configuration, and external contracts; see
[`ROLLBACK.md`](ROLLBACK.md). Infrastructure rollback cannot retract a disclosure.
Classify every substep independently; migrations, DNS/IAM, messages/webhooks,
billing, and first disclosure may still be gated. If a step spends money or makes
an external change that cannot be reliably undone, follow *Irreversible external
actions are preview-first* in [`AGENTS.md`](../AGENTS.md): preview exact scope,
obtain fresh scope-bound authorization, execute with bounds and replay safety,
and record a sanitized outcome. That authorization never grants authority for
the owner-only actions listed below.

## Self-authorized when ALL THREE hold

1. **Ample testing.** The change is on `master`, green on CI (Tests / Lint &
   Typecheck / Build), and its risky parts were exercised directly — e.g. a DB
   migration was applied to a representative non-production database and its
   behaviour verified (production application remains a separately owner-gated
   action; see [`migration-rollback.md`](migration-rollback.md)), and the build's
   own guards pass (no default/guessable secret baked in, no `localhost` leak —
   see [`../SECURITY.md`](../SECURITY.md)).
2. **Snapshot verification.** A **before/after snapshot** of the user-facing
   change was produced and reviewed (what exists → what ships), so the visible
   effect is known in advance rather than discovered live. This is the
   storyboard precept applied to a deploy — see [`STORYBOARD.md`](STORYBOARD.md).
3. **Post-deploy sanity check.** Immediately after publishing, a live check
   confirms the change landed and nothing obvious regressed: the deployed build
   reports the new commit, and the specific feature is spot-checked on the live
   URL. Run `make verify-live BASE=https://… EXPECT=<build-id>`; pass
   `BASE_ALT=https://…` when a custom hostname and provider origin both reach the
   artifact. Static pages can use `LIVE_PATH=/ LIVE_CONTAINS=1`, and a large
   seekable asset can add `RANGE=/path/to/asset`. The check is bounded and fails
   unless **every** hostname serves the expected build in the same polling pass.

   The verifier deliberately sends a browser-like user agent and `Cache-Control:
   no-cache`, waits for CDN propagation before asserting, does not follow an
   access/login redirect, caps response bytes as well as time, and never logs the
   response body or an unlisted path. Provenance mode also requires a JSON content
   type. A range check must return `206` with `Content-Range`; a successful page
   fetch cannot prove that a video or other large artifact is complete or seekable.
   If a stack does not yet expose a build marker, add one before claiming this
   gate—the expected text appearing somewhere else in a response is not deploy
   provenance.

Before sharing any deploy URL, classify it as public, unlisted, or authenticated
review. `noindex` plus an unguessable link is **not** privacy; unpublished, client,
reviewer, or competitively sensitive material requires a real access boundary. See
[`UNLISTED_PUBLISHING.md`](UNLISTED_PUBLISHING.md).

When 1–3 hold, the deploy is complete — rollback is **not** a precondition, and
none is expected. If the post-deploy check *fails*, use
[`ROLLBACK.md`](ROLLBACK.md). Re-promote a previous artifact only when its
current-schema compatibility is proved; otherwise use a forward fix or a
coordinated recovery. Application rollback does not undo database writes,
messages, webhooks, payments, permissions, credentials, or disclosure.

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
