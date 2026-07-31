# Encrypted local areas

Hold sensitive local data **inside** the {{ project_name }} repo — encrypted at
rest — so it is versioned, pushable, and backed up like everything else, without
ever leaking plaintext. Built on [git-crypt](https://github.com/AGWA/git-crypt):
designated paths are transparently encrypted on the way into git and decrypted in
your working tree once the repo is unlocked.

This capability is **opt-in** (`include_encrypted_local_areas=yes` at generation).
It complements the [`secret_vault`](SECRET_VAULT.md) add-on: `secret_vault` stores
and recovers the *key* redundantly; this doc is about the *areas* the key protects
and the guard that keeps them honest.

## What you get

| Piece | Path | Role |
|-------|------|------|
| Encrypted area | `{{ encrypted_paths }}/` | Everything here is encrypted at rest. |
| Filter designation | `{{ encrypted_paths }}/.gitattributes` | `* filter=git-crypt diff=git-crypt`, minus the plaintext pointers (`!filter !diff`). |
| Pointer README | `{{ encrypted_paths }}/README.md` | Plaintext, key-free, self-describing (what/where-the-key-lives/rules). |
| Fail-closed guard | `scripts/git-crypt-guard.sh` | Refuses to commit plaintext into an encrypted area when the key isn't loaded. |
| Pre-commit hook | `.githooks/pre-commit` | Runs the guard, then the base `make precommit` gate. |

## The threat model, in one line

git-crypt only encrypts a file if its **clean filter is active**. Clone the repo
and forget to `git-crypt unlock`, and a file you drop under `{{ encrypted_paths }}/`
commits **in the clear** — silently. The pre-commit guard exists to turn that
silent leak into a loud, blocked commit.

## One-time setup (per repository)

git-crypt is a **host** tool (like `git` itself); install it once:

```
# macOS
brew install git-crypt
# Debian/Ubuntu
sudo apt-get install git-crypt
```

Initialize and stash the key **before** you put anything real in the area:

```
git-crypt init                          # generates the repo's symmetric key
git-crypt export-key /tmp/{{ github_repo }}.key   # a 0600 copy to stash, then delete
```

Store that key in **both** durable places, then shred the temp copy:

- **{{ password_manager }}** — the shareable, recoverable copy of record.
- The **OS keychain** — the everyday local copy.

If the `secret_vault` add-on is enabled, do all of that in one step (it names the
item `git-crypt: {{ github_repo }}` and writes {{ password_manager }} + the OS
keychain + a locked backup, cross-checked by fingerprint):

```
./scripts/git-crypt-key.sh store        # export THIS repo's key → the vault
```

Then remove the temp key file (`shred -u` / `rm -P`) — the key must never sit
around in the clear or land in git.

## Everyday use

```
make hook-install                       # activate .githooks (guard + base gate)
git-crypt unlock                        # decrypt the working tree (key from vault)
# ...edit files under {{ encrypted_paths }}/ ...
git add {{ encrypted_paths }}/notes.md
git commit                              # guard verifies the staged blob is encrypted
```

On a **fresh clone** (new machine), restore the key and unlock:

```
# with secret_vault:
./scripts/git-crypt-key.sh restore --unlock
# or, with a key file you exported:
git-crypt unlock /path/to/{{ github_repo }}.key
```

Confirm what is protected:

```
git-crypt status -e                     # list the encrypted files
```

## The pre-commit guard (fail-closed)

`.githooks/pre-commit` runs `scripts/git-crypt-guard.sh` on every commit. For each
staged file that `.gitattributes` marks `filter=git-crypt`, the guard reads the
**staged blob's** first 10 bytes and checks for git-crypt's encrypted-blob magic
(`\0GITCRYPT\0`). If a guarded file is staged as plaintext — the key isn't loaded,
or git-crypt was never set up — the guard **blocks the commit**:

```
✗ pre-commit: refusing to commit PLAINTEXT into an encrypted area.
These staged files live under a git-crypt path but are NOT encrypted:
  {{ encrypted_paths }}/notes.md
...
```

It is pure `git` plumbing (needs no git-crypt binary), so it still fires on a
machine where git-crypt is missing. It runs on the **host** — nothing to run in
Docker. Bypass only when you know the file is genuinely non-sensitive:
`git commit --no-verify`.

## Adding more encrypted areas

`{{ encrypted_paths }}/` is the default area. To add another, drop a `.gitattributes`
into the new directory with the same three lines (encrypt `*`, keep `README.md`
and `.gitattributes` in the clear) and a plaintext pointer `README.md`. The guard
and `git-crypt status` pick it up automatically — no code changes.

## The no-public-remote rule

**A repo with encrypted areas stays on a PRIVATE remote.** git-crypt's ciphertext
is strong, but encryption is defense in depth, not a licence to publish: a public
remote exposes the ciphertext to offline attack forever and forecloses key
rotation as a real remedy. Keep the remote private; treat any push to a public
remote as an incident (rotate the key, scrub the remote).

## Rotation & recovery

- **Rotate** on suspected key exposure (a key that ever touched chat, a log, a
  commit, or an untrusted machine is compromised): generate a new key, re-`init`
  in a fresh clone, re-add the files so they re-encrypt under the new key, and
  update {{ password_manager }} + the OS keychain. Old clones keep the old key —
  treat them as burned.
- **Recover**: any single durable copy restores the key. With `secret_vault`,
  `./scripts/git-crypt-key.sh restore` pulls it from {{ password_manager }} → the
  OS keychain → the on-disk backup, fingerprint-verified. See
  [SECRET_VAULT.md → Recovery](SECRET_VAULT.md#recovery).

## Related

- [SECRETS.md](SECRETS.md) — the secrets house contract (never plaintext-commit,
  redundancy + fingerprint, runtime injection).
- [SECRET_VAULT.md](SECRET_VAULT.md) — `secret-store` / `secret-get` /
  `git-crypt-key` tooling that backs the key.
- [SECURITY.md](../SECURITY.md) — reporting + fail-closed config.
