# Adding a new stack profile

A stack profile is everything that differs by tech choice. The universal
meta-layer in `template/` stays untouched; you only add a directory under
`stacks/`.

## Steps

1. **Create `stacks/<your-stack>/`.** Anything here overlays (and can override)
   the meta-layer when this stack is selected.

2. **Ship the contract the meta-layer expects.** The universal pieces assume:
   - A `docker-compose.yml` with a `postgres` service and a `storyboard`
     profile, plus tool profiles for your toolchains.
   - A `Makefile` exposing at least: `up`, `down`, `migrate`, `test`,
     `lint`, `precommit`, `storyboard`, `hook-install`.
   - A `.github/workflows/ci.yml` whose job **display names** are exactly
     `Tests` and `Lint & Typecheck` (and `Build` if you have a build gate) —
     `auto-merge.yml` gates on those names.
   - `backend/scripts/migrate.sh` tracking applied versions in
     `{{ migrations_table }}`, and a `backend/migrations/001_init.sql`.

3. **Honour "no host SDKs."** Every toolchain is a profiled Compose service
   invoked from the Makefile via `docker compose --profile <p> run --rm <svc>`.

4. **Use tokens, not literals.** Reference `{{ project_name }}`,
   `{{ project_slug }}`, `{{ db_name }}`, ports, etc. so the generator fills
   them in. Filenames may contain tokens too (e.g.
   `services/lib/{{ project_slug }}_services.dart`).

5. **Register the choice.** Add the directory name to the `stack` list in
   `firestarter.config.json`.

6. **Document gotchas inline.** The value of a stack profile is the hard-won
   knowledge baked into its comments (image pins, cache reloads, ARM64 notes).

## Test it

```bash
./bin/firestart.sh --defaults --set stack=<your-stack> --output /tmp/smoke
# then in the output: make up && make migrate && make precommit
```

Update [docs/ANATOMY.md](ANATOMY.md) with a table for the new stack.

## Non-DB stacks

The contract above assumes a DB-backed app, but a stack needn't have one (see
`chrome-extension` — a browser extension is pure client code). For a DB-less
stack:

- **Skip `postgres` / `backend/` / migrations.** Don't ship `migrate.sh` or
  `001_init.sql`; make `make migrate` a documented no-op and adapt `up`/`down`
  to something meaningful for your stack (e.g. build + "load unpacked").
- **Keep the required job names.** CI must still expose `Tests` /
  `Lint & Typecheck` (+ `Build`) — `auto-merge.yml` gates on them regardless of
  what's underneath.
- **Override, don't fight, the meta-layer.** A few universal pieces are
  DB-flavored: the `storyboard.yml` workflow waits on postgres + runs migrations,
  so ship your own `.github/workflows/storyboard.yml` that just builds and runs
  the harness. Some docs (`migration-rollback.md`, DB notes in `CLAUDE.md`) will
  stamp but be inert — that's an accepted trade-off, not a bug.
- **Still honour the storyboard precept** (hard rule #6): ship a harness that
  screenshots your real UI, even one with no server (the extension harness opens
  the built `dist/sidebar.html`).
