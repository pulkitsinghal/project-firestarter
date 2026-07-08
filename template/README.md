# {{ project_name }}

{{ project_tagline }}

Scaffolded from [project-firestarter](https://github.com/{{ github_owner }}/project-firestarter)
on the **{{ stack }}** stack.

## Quickstart

You need only Docker — no host language toolchains
([full host requirements](docs/HOST_REQUIREMENTS.md)).

```bash
make up            # boot the stack (db + app services)
make migrate       # apply forward-only migrations
make hook-install  # activate the opt-in git hooks
make help          # list every dev command
```

App: http://localhost:{{ port_web }} · API: http://localhost:{{ port_api }}

## How we work

- **No host SDKs.** Every toolchain runs in a Docker Compose profile. `make`
  targets wrap the `docker compose --profile <p> run --rm <svc>` calls.
- **Validate locally before pushing:** `make precommit` runs every CI gate.
- **Conventional Commits**, enforced by the `commit-msg` hook and CI.
- **AI-reviewed PRs.** `ai-pr-review.yml` posts a verdict; `auto-merge.yml`
  squash-merges green PRs labelled `auto-merge`.

See [AGENTS.md](AGENTS.md) (full engineering brief), [CONTRIBUTING.md](CONTRIBUTING.md)
(short version), and [ARCHITECTURE.md](ARCHITECTURE.md).

## CI secrets

The AI reviewer needs `ANTHROPIC_API_KEY`. Never paste secret values anywhere —
set them with `gh secret set`. See [docs/ci-secrets.md](docs/ci-secrets.md).
