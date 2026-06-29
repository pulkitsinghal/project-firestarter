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
