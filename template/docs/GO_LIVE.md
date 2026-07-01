# Go-Live Runbook

A repeatable checklist to stand {{ project_name }} up from a clean slate, verify
it, and take it live. Everything runs in Docker — no host SDKs.

## 1. Run it (clean slate)

```bash
make down      # drop any prior volumes (optional; destroys local data)
make up        # start the stack
make migrate   # apply forward-only migrations (idempotent)
```

The services bind to offset host ports (web {{ port_web }}, api {{ port_api }},
db {{ port_db }}, redis {{ port_redis }}) so this stack coexists with others —
see [README.md](../README.md) for the exact URLs and a first-request smoke check.

## 2. Verify

```bash
make precommit   # the same gates CI runs (lint + typecheck + tests)
make test        # the test suite
make storyboard  # Playwright screenshots → storyboard/output/ (visual check)
```

Green locally ⇒ CI will be green (`make precommit` mirrors the CI gates exactly).

## 3. Before you go live

- [ ] **Secrets set, never committed.** `gh secret set ANTHROPIC_API_KEY` (and any
      others) — see [docs/ci-secrets.md](ci-secrets.md). Confirm `make secret-scan`
      is clean.
- [ ] **Branch protection / auto-merge** configured on `master` (required checks:
      Tests · Lint & Typecheck · Conventional Commits) — see [AGENTS.md](../AGENTS.md).
- [ ] **Cut the first release:** bump `VERSION`, run `make version-sync`, update
      `CHANGELOG.md`, tag (`git tag -a vX.Y.Z`) — see [CHANGELOG.md](../CHANGELOG.md).
- [ ] **Deploy path rehearsed:** `make up && make deploy` opens a public Cloudflare
      quick-tunnel (no account, no secrets) — see [DEPLOY.md](../DEPLOY.md).
- [ ] **Backups decided** before real data lands — see
      [docs/OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) ("database backup & restore
      strategy") and [docs/migration-rollback.md](migration-rollback.md).

## 4. If something goes wrong

Undo a bad migration the forward-only way — see
[docs/migration-rollback.md](migration-rollback.md) — and write a blameless
postmortem under `docs/postmortems/`.
