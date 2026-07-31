# `encrypted_local_areas` add-on (contributor notes)

> This file documents the add-on for **firestarter maintainers**. It lives above
> `common/`, so the generator does **not** stamp it into projects. The user-facing
> runbook is `common/docs/ENCRYPTED_LOCAL_AREAS.md`, which *does* stamp into
> `<project>/docs/`.

## What it is

A **stack-agnostic**, opt-in capability that lets a stamped project hold sensitive
local data **inside** the repo, encrypted at rest with
[git-crypt](https://github.com/AGWA/git-crypt), and still be pushed/backed up. It
lifts the generic *convention* — not any project's content — from sibling repos
that keep encrypted `knowledge/**`-style areas.

It **complements** `secret_vault`: that add-on stores/recovers the git-crypt *key*
redundantly (`git-crypt-key.sh`); this one designates the encrypted *areas*, ships
the plaintext pointer, and enforces the "no plaintext in an encrypted area" rule.
They are independent (either can be enabled alone) and cross-reference in docs.

## Layout (all under `common/`, stamped to `<project>/`)

```
common/
  {{ encrypted_paths }}/.gitattributes   git-crypt filter designation (`* filter=git-crypt`)
                                         + `!filter !diff` for the plaintext pointers
  {{ encrypted_paths }}/README.md        plaintext, key-free pointer / SECURITY-README
  scripts/git-crypt-guard.sh             fail-closed guard (host git plumbing, bash)
  .githooks/pre-commit                   SUPERSET of template/.githooks/pre-commit:
                                         runs the guard, then the base make-precommit gate
  docs/ENCRYPTED_LOCAL_AREAS.md          setup + hooks + unlock/rotation runbook
```

## Design notes / gotchas

- **Per-area `.gitattributes`, not top-level.** git-crypt honours nested
  `.gitattributes`, so the encryption rule lives *inside* `{{ encrypted_paths }}/`.
  That avoids clobbering the template's top-level `.gitattributes` (the LF-pinning
  rules) and keeps each area self-contained. Add another area = drop another dir
  with the same three lines; no code change.
- **The pre-commit hook is a deliberate superset.** git runs exactly one
  `pre-commit`, and the template already ships one (`make precommit`). To add the
  fail-closed guard *and* keep the base gate, this add-on overlays a superset that
  runs both. Step 2 mirrors `template/.githooks/pre-commit` — **keep them in sync**
  if the base gate changes. The contract test asserts the superset still calls the
  guard and `make precommit`.
- **The guard is `git` plumbing, key-free.** It checks each staged blob under a
  `filter=git-crypt` path for git-crypt's 10-byte magic header
  (`\0GITCRYPT\0` = hex `00 47 49 54 43 52 59 50 54 00`). No git-crypt binary
  needed, so it still fires when git-crypt was never installed. Host-only (needs
  the real index) — nothing runs in Docker.
- **Tokens.** `{{ encrypted_paths }}` (the area dir, default `private`) and
  `{{ password_manager }}` (default `1Password`) are declared in
  `firestarter.config.json`; the key name reuses `{{ github_repo }}`. No literals.

## Verify

- `bash -n common/scripts/git-crypt-guard.sh`; `sh -n common/.githooks/pre-commit`.
- `tests/test_encrypted_local_areas_contract.py`: default-off, every stack stamps
  the exact files, the guard blocks a plaintext staged file and passes an
  encrypted (magic-prefixed) one, and the superset hook keeps the base gate.
- Stamped-output leak grep is covered by the repo's `Verify before you commit`
  step in `AGENTS.md`.
