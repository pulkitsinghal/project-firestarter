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
- The anonymous-identity and data-exposure invariants in `ARCHITECTURE.md` are
  part of the security surface — a violation is a vulnerability, not a bug.

## Scope

The latest `master` is supported. Forward-only migrations mean fixes land as new
numbered migrations, never edits to applied ones.
