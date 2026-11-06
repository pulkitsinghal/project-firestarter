# Open Questions & Deferred Decisions

A running log of things we've consciously *not* decided yet, and why. When a
question is answered, move it to the "Resolved" section with the decision and
date — don't delete it (the trail is the value).

An **unverified empirical claim** — an assertion about the world (what builds,
what a toolchain needs, what a tier permits) that no one has checked — belongs
here as an open question, not in `AGENTS.md` as an invariant, until it carries a
verified-on date and the exact command that reproduces it. See *Policy vs.
empirical claims* in `AGENTS.md`.

## Format

```
### Q: <the question>
- **Context:** why this came up
- **Options:** the choices on the table
- **Leaning:** current best guess (if any)
- **Blocked on:** what we need to decide
```

## Open

### Q: _example — which auth model for the MVP?_
- **Context:** scaffolded; not yet decided.
- **Options:** anonymous device-id tokens · email/OTP · third-party.
- **Leaning:** _tbd_
- **Blocked on:** product scope.

### Q: database backup & restore strategy?
- **Context:** migrations are forward-only, so a data-destroying migration may
  need a *restore*, not just a revert (see `docs/migration-rollback.md`).
- **Options:** managed-provider snapshots · scheduled `pg_dump` to object
  storage · PITR / WAL archiving.
- **Leaning:** _tbd — decide before the first production data lands._
- **Blocked on:** where the DB is hosted in production.

## Resolved

_(move answered questions here with the decision + date)_
