# Secrets — house contract (do not violate)

The standing rules for handling **any** secret in {{ project_name }} — API keys,
tokens, passwords, signing keys, git-crypt repo keys. This is a hard contract for
humans and AI agents alike; `AGENTS.md` points here. It complements
[SECURITY.md](../SECURITY.md) (reporting + fail-closed config) and the
[Secret Vault add-on](SECRET_VAULT.md) (the tooling that makes the safe path easy).

## The rules

1. **Never plaintext-commit a secret.** No secret value in git history, a commit
   message, a PR body, an issue, a chat transcript, a log line, or a screenshot.
   Anything that lands in one of those is **compromised** and must be rotated.
   - Repo-embedded secrets (e.g. encrypted `knowledge/**` IP) use **git-crypt**;
     the on-disk backup dir (`~/.secret-vault/`) is **git-ignored**, never tracked.
   - `.env` is git-ignored; only `.env.example` (placeholders) is committed.
   - A pre-commit **secret scan** (gitleaks) backs this up — it is not a substitute
     for the rule.

2. **Redundancy + fingerprint integrity.** A durable secret lives in **≥2 durable
   stores plus a backup**, each cross-checked by the **same sha256 fingerprint**.
   Use `secret-store` — it writes 1Password + the OS secret store + an on-disk
   backup and **fails closed** if fewer than two copies verify. One lost or
   corrupted store must never mean an unrecoverable secret.

3. **Never echo, log, print, or embed a secret value.** Do not `echo`/`cat` a
   secret, write it to stdout for a human to read, put it in a URL or query string,
   or pass it as a **command-line argument** (argv is world-readable via `ps`).
   Provide secrets to tools via **stdin**, a **file read**, or the runtime
   injection below. Only a secret's **fingerprint** (not the value) may be printed.

4. **Runtime injection, not materialization.** To use a secret, stream it directly
   into the consuming process — `secret-get <name> --exec ENVVAR -- <cmd>` sets the
   value in the child's environment only, then exec's. Prefer this over writing the
   value to a file or exporting it into a long-lived shell. When a tool truly needs
   a path, write to a locked (`0600` / ACL-restricted) file and delete it after.
   This is the local-workstation analogue of a dynamic secret reference (fetch at
   point of use; never park plaintext in the environment or the agent's context).

5. **Least privilege + per-service naming.** One secret per purpose, named for its
   service (`STRIPE_API_KEY`, `git-crypt: <repo>`), scoped to the narrowest role
   that works. Don't reuse one credential across services; don't grant an
   OS-store account broader reach than it needs. CI secrets go in via
   `gh secret set` (see [ci-secrets.md](ci-secrets.md)), never pasted anywhere.

6. **Rotation + recovery are planned, not improvised.** Rotate long-lived secrets
   on a cadence (**≥ every 90 days**) and immediately on any suspected exposure.
   Re-run `secret-store` to rotate in place across all stores. Know the recovery
   path *before* you need it — any single store restores the secret
   ([SECRET_VAULT.md → Recovery](SECRET_VAULT.md#recovery)).

## Quick reference

| Do | Don't |
|----|-------|
| `op read … \| secret-store NAME` | `secret-store NAME "the-value"` (value in argv) |
| `secret-get NAME --exec ENV -- cmd` | `export ENV=$(secret-get NAME)` in a shared shell |
| `secret-get NAME --file out --source op` | `secret-get NAME > committed-file` |
| Store to ≥2 stores + backup, verify sha256 | Keep the only copy in one place |
| git-crypt for repo-embedded secrets | Commit a plaintext key / `.env` |
| Print the **fingerprint** | Print / log the **value** |
| Rotate on exposure or ≥90 days | Leave a leaked secret live |

## If a secret leaks

1. **Rotate it now** at the source (provider / re-key git-crypt). The old value is
   dead the moment it is exposed — do not try to "un-leak" it.
2. Re-store the new value with `secret-store` (re-establishes redundancy + a new
   fingerprint).
3. Purge the exposure where feasible (delete the log/artifact) and note it — but
   treat rotation, not deletion, as the fix.
