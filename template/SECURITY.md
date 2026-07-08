# Security Policy

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.** Report privately so
the fix can ship before the details are public:

- Preferred: open a private advisory at
  <https://github.com/{{ github_owner }}/{{ github_repo }}/security/advisories/new>.
- Include: affected component, reproduction steps, and impact.

You'll get an acknowledgement and a coordinated disclosure timeline.

## Handling secrets

- **Never paste a secret value into a chat, issue, PR, or commit.** Once it's in
  a transcript or git history it's compromised and must be rotated. Provide CI
  secrets via `gh secret set` — see [docs/ci-secrets.md](docs/ci-secrets.md).
- **Never bake a default or guessable secret** into deploy configs, Compose
  files, or code. A hardcoded demo/JWT/signing key becomes a live credential the
  moment the stack is exposed. Read every secret from the environment (`gh secret`
  / a git-ignored `.env`), **fail closed** when it's unset, and never fall back to
  a baked-in default. The bundled `deploy.yml` uses no secrets by design (the
  Cloudflare quick-tunnel is anonymous) — keep it that way.
- The anonymous-identity and data-exposure invariants in `ARCHITECTURE.md` are
  part of the security surface — a violation is a vulnerability, not a bug.

## Scope

The latest `master` is supported. Forward-only migrations mean fixes land as new
numbered migrations, never edits to applied ones.
