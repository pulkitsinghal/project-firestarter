# `{{ encrypted_paths }}/` — encrypted local area

This directory is an **encrypted local area** for {{ project_name }}. Everything
committed here is transparently encrypted **at rest** by
[git-crypt](https://github.com/AGWA/git-crypt): your working tree shows plaintext
once the repo is unlocked, but what git stores — and what any remote or backup
ever receives — is ciphertext. That lets this repo safely hold sensitive local
data (private notes, sample records, local-only config) and still be pushed and
backed up.

This `README.md` and the sibling `.gitattributes` are the only files kept in the
clear (`!filter !diff`), so the area stays self-describing even when locked.

## Where the key lives (never in git)

The repository's git-crypt **symmetric key** is stored in **two** durable places:

- **{{ password_manager }}** — the shareable, backed-up copy of record.
- The **OS keychain** on each trusted machine — the everyday local copy.

It is **never** committed, printed, or pasted into chat, PRs, or issues. See
[`../docs/ENCRYPTED_LOCAL_AREAS.md`](../docs/ENCRYPTED_LOCAL_AREAS.md) for the
full setup, unlock, backup, and rotation runbook.

## Rules

- **Never push a repo with encrypted areas to a PUBLIC remote.** Encryption is
  defense in depth, not a licence to publish — keep the remote private.
- **Unlock before you edit.** `git-crypt unlock` (key from {{ password_manager }}
  + OS keychain). If you skip it, the fail-closed pre-commit guard refuses the
  commit rather than leak plaintext.
- **No secrets in this `README.md` or in `.gitattributes`** — they are plaintext.
- Anything else you drop under `{{ encrypted_paths }}/` is encrypted the moment
  it is staged.

## Verify it is working

```
git-crypt status            # list which files are encrypted vs. not
git-crypt status -e         # only the encrypted ones
```

A staged file here should show as **encrypted**. As a key-free spot check,
`git show :<file>` on a committed file in this area begins with the bytes
`GITCRYPT` when the ciphertext — not your data — is what actually landed in git.
