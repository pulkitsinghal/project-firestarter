# CI Secrets — how to provide them

**Never paste a secret value into a chat, issue, PR, or commit.** Once it's in a
transcript or git history it's effectively compromised and must be rotated. Use
one of the methods below so the literal value never leaves your machine in
plaintext.

## Secrets this repo uses

| Name | Type | Used by | Required? |
|------|------|---------|-----------|
| `ANTHROPIC_API_KEY` | Actions secret | `ai-pr-review.yml` (PR review verdict) | Yes, for real AI reviews |
| `CLAUDE_MODEL` | Actions **variable** | `ai-pr-review.yml` (model id) | Optional (defaults to `{{ claude_model }}`) |

Without `ANTHROPIC_API_KEY` the reviewer still runs but degrades to a
`NON-BLOCKING` stub. With it set, you get a genuine review and `auto-merge.yml`
gates on the real verdict.

## Preferred: set it yourself (value never enters a transcript)

The CLI reads the value from a hidden prompt — not echoed, not in shell history:

```bash
gh secret set ANTHROPIC_API_KEY --repo {{ github_owner }}/{{ github_repo }}
# paste when prompted

# optional: pin the review model
gh variable set CLAUDE_MODEL --repo {{ github_owner }}/{{ github_repo }} --body "{{ claude_model }}"
```

Or in the GitHub web UI: **Settings → Secrets and variables → Actions → New
repository secret** (and the **Variables** tab for `CLAUDE_MODEL`).

## Rotation

If a secret value ever appears in a log, transcript, or commit, rotate it
immediately (issue a new key, update the secret, revoke the old one).
