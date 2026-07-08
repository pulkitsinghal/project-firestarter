# Migration rollback procedure

{{ project_name }}'s migrations are **forward-only by design**: each
`backend/migrations/NNN_topic.sql` is appended to the history, and the
`{{ migrations_table }}` table tracks what has been applied (see
`backend/scripts/migrate.sh`). This doc covers the rare case where you must undo
one — treat reaching for it like a production incident.

## Principles

- **Reverse migrations are special, not routine.** If you reach for this doc,
  announce it, file an issue, and write a postmortem afterward
  (`docs/postmortems/`).
- **Forward-only stays the rule.** A rollback is a *forward* migration that
  undoes a previous one. You do NOT delete or edit the old migration file.
- **Never edit an applied migration** — the only exception is provably
  idempotent hardening (adding `IF NOT EXISTS` guards); see `AGENTS.md`.

## A rollback is a forward migration

Two artifacts:

1. A new migration `NNN_revert_<topic>.sql`, numbered after the latest applied
   version, that semantically undoes the change.
2. A `{{ migrations_table }}` history row — added automatically when you apply
   the revert via `make migrate`. The original migration's row stays.

## Procedure

### 1. Decide whether to roll back
- Is the system actually broken in production, or just behaving unexpectedly?
- Can a forward *fix* land faster than a revert? Often yes.
- If the migration only ADDED objects (tables, columns, indexes, functions), a
  forward "drop" is mechanically simple.
- If it DROPPED objects or rewrote data, recovery may require a backup restore.
  **Stop and consult your backup procedure first** (see `docs/OPEN_QUESTIONS.md`
  — "database backup & restore strategy").

### 2. Write the revert migration
Create `backend/migrations/NNN_revert_<topic>.sql` where `NNN` is the next
sequential number. Undo only what the original did. Example:

```sql
-- 007_revert_006_drop_email.sql
-- Reinstates the column 006 dropped. Forward migration; does NOT touch 006.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
```

For a function revert, `CREATE OR REPLACE FUNCTION` the previous body. For a
dropped column you can restore the *structure* but not the *data*.

### 3. Apply via the normal runner
```bash
make migrate
```
The runner records the revert in `{{ migrations_table }}`; the original row
stays. Never hand-edit the history table outside the emergency step below.

> **Applying to a hosted / managed Postgres (Supabase Cloud, RDS, …).** The runner
> above targets the local `docker compose` stack. For a managed database, apply the
> **same forward-only files incrementally** against its connection string — one
> un-applied file per version, each in its own transaction, recording the
> `{{ migrations_table }}` row as you go:
>
> ```bash
> psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f backend/migrations/NNN_x.sql
> ```
>
> Do **NOT** apply prod by dumping the local schema and restoring it onto the
> managed DB. A dump→restore is not forward-only: it clobbers managed-only state
> (roles, extensions, data), skips the history table, and drifts prod from the
> migration sequence every other environment ran. Incremental-apply keeps every
> environment converged on the same ordered migrations.

### 4. Backfill data if needed
If the revert reinstates a column, follow up with a commit that repopulates it
from another source (an event log, a backup snapshot). Bundle the structural and
data steps in one migration only if the data source is queryable from SQL;
otherwise split them.

### 5. Emergency database surgery (last resort)
If production is on fire and you cannot wait to write a clean revert, connect
directly and apply SQL by hand:

```bash
docker compose exec -T postgres psql -U postgres -d {{ db_name }}
```

Then IMMEDIATELY converge every environment:

1. Commit the equivalent migration to `backend/migrations/` so other
   environments apply it the normal way.
2. Record it as applied in the same psql session so the runner won't re-run it:
   ```sql
   INSERT INTO {{ migrations_table }} (version)
   VALUES ('NNN_revert_<topic>') ON CONFLICT DO NOTHING;
   ```
3. Open a PR for the migration file with a Test plan referencing the incident.

If a migration applied only partially (crashed mid-run): manually undo the
partial side effects, then re-run `make migrate` — it skips the versions already
recorded and picks up where it left off.

### 6. Write the postmortem
Land a blameless postmortem under `docs/postmortems/<date>-<slug>.md` (see
`docs/postmortems/TEMPLATE.md`):

- Why did the original migration cause harm?
- Why didn't testing / CI catch it?
- What invariant was violated, and what guardrail now blocks recurrence?

## See also
- `AGENTS.md` — commit / branch / push policy and the "never edit an applied
  migration" rule.
- `backend/scripts/migrate.sh` — the runner that records versions in
  `{{ migrations_table }}`.
- `docs/postmortems/TEMPLATE.md` — the postmortem template.
