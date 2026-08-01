# Secret Vault add-on

Cross-platform, dependency-light **redundant secret storage** for {{ project_name }}.
Enabled at generation with `include_secret_vault=yes` (stack-agnostic).

Every secret — a git-crypt repo key, an API token, a signing key — is stored in
**several durable places at once** and cross-checked by **sha256 fingerprint**, so
no single lost or corrupted store leaves you unable to recover it. The same tool
retrieves secrets for runtime use by **streaming them straight into the consuming
command**, so the value never lingers in a file, an environment, or a shell history.

> This generalises an ad-hoc `git-crypt-key-store` helper (macOS-only, two stores)
> into a portable tool: any named secret, three durable stores, fingerprint
> verification, safe runtime injection, and macOS **+ Windows + Linux** support.

## Concept: defense-in-redundancy + fingerprint integrity

```
             ┌──────────────┐   store (all) + verify (read-back sha256)
   secret ──▶│ secret-store │──┬──▶ 1Password (op document)          ─┐
             └──────────────┘  ├──▶ OS secret store (per-platform)    ├─ same sha256
                               └──▶ on-disk backup (locked-down)     ─┘   or it FAILS

             ┌──────────────┐   read one (with fallback) + verify sha256
   runtime ◀─│  secret-get  │◀──── 1Password → OS store → backup
             └──────────────┘        └─ streams into --exec / --file / stdout
```

- **Redundancy floor:** at least **two durable copies** must land or the store
  operation fails closed. The on-disk backup is the recovery floor; 1Password and
  the OS secret store are the everyday sources.
- **Integrity:** the canonical fingerprint is the sha256 of the raw secret bytes.
  Every copy is read back and must hash to the same value. A recorded, *non-secret*
  fingerprint index (`~/.secret-vault/index/<slug>.sha256`) lets `secret-get`
  verify a single-store read without pulling all three.
- **No plaintext leakage:** the value is never an argument, never echoed or logged,
  never placed in an env var or URL except the one runtime injection the consumer
  needs. Only the fingerprint and per-store status are ever printed.

## Platform matrix

| Layer | macOS | Linux | Windows |
|-------|-------|-------|---------|
| Password manager | `op` (1Password CLI) | `op` | `op` |
| OS secret store | login **Keychain** (`security`) | **Secret Service** / libsecret (`secret-tool`) | **Credential Manager** (advapi32 `CredWrite`/`CredRead`, no external module) |
| On-disk backup | `~/.secret-vault/backups/*.secret`, `0600` | same, `0600` | `%USERPROFILE%\.secret-vault\backups\*.secret`, **DPAPI-encrypted** + ACL-locked |
| Scripts | `scripts/*.sh` | `scripts/*.sh` | `scripts/*.ps1` |

`op` and `git-crypt` are already cross-platform; only the OS-secret-store layer is
platform-specific, and each script picks the right mechanism automatically.

Optional environment overrides (all platforms):

| Env var | Meaning |
|---------|---------|
| `SECRET_VAULT_HOME` | Base dir for `backups/` and `index/` (default `~/.secret-vault`). |
| `SECRET_VAULT_OS_ACCOUNT` | OS-store account label (default `secret-vault`). |
| `SECRET_VAULT_OP_VAULT` | 1Password vault to store items in. |
| `SECRET_VAULT_MACOS_KEYCHAIN` | Target a specific macOS keychain instead of `login`. |

## Usage

### Store a secret (POSIX)

```bash
# from a password manager, piped in (never on the command line):
op read 'op://Private/some-api/credential' | ./scripts/secret-store.sh SOME_API_KEY

# from a file, or freshly generated:
./scripts/secret-store.sh SIGNING_KEY --file ./signing.key
./scripts/secret-store.sh SESSION_SECRET --generate 32
```

Windows (PowerShell):

```powershell
op read 'op://Private/some-api/credential' | .\scripts\secret-store.ps1 SOME_API_KEY
.\scripts\secret-store.ps1 SESSION_SECRET -Generate 32
```

Output (value never shown):

```
secret: SOME_API_KEY
fingerprint (sha256): 8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4
  1Password              : ok
  Keychain (macOS)       : ok
  backup (~/.secret-vault/backups/SOME_API_KEY.secret): ok

✓ 3 durable copies, all fingerprints match (8f434346648f…)
```

### Use a secret at runtime (prefer `--exec`)

```bash
# Inject as an env var into the child ONLY, then exec — never in argv/files:
./scripts/secret-get.sh SOME_API_KEY --exec API_KEY -- ./server --port 8080

# Or write a binary secret to a locked (0600) file for a tool that needs a path:
./scripts/secret-get.sh SIGNING_KEY --file ./run/signing.key

# Or stream to stdout for a pipe:
./scripts/secret-get.sh SOME_API_KEY | some-consumer --stdin
```

Windows:

```powershell
.\scripts\secret-get.ps1 SOME_API_KEY -Exec API_KEY -- .\server.exe --port 8080
```

`secret-get` reads **1Password → OS store → backup** in order (override with
`--source`), verifies the fingerprint, and only then hands the value over.

### git-crypt convenience wrapper

Stores/restores a repo's git-crypt symmetric key under the conventional name
`git-crypt: <repo>` (backward-compatible with the old helper):

```bash
./scripts/git-crypt-key.sh store              # export THIS repo's key → vault
./scripts/git-crypt-key.sh store scribe --key ./scribe.key
./scripts/git-crypt-key.sh restore --unlock   # vault → key → `git crypt unlock`
```

```powershell
.\scripts\git-crypt-key.ps1 store
.\scripts\git-crypt-key.ps1 restore -Unlock
```

This is the primary use case: keys that decrypt the encrypted `knowledge/**`
paths. Because it is generic, the same tool secures any secret.

## Recovery

Any single store is sufficient to recover the secret; all three would have to be
lost at once to lose it.

```bash
# Recover from a specific store and verify against the recorded fingerprint:
./scripts/secret-get.sh SOME_API_KEY --source op      --file ./recovered
./scripts/secret-get.sh SOME_API_KEY --source os      --file ./recovered
./scripts/secret-get.sh SOME_API_KEY --source backup  --file ./recovered
```

If the fingerprint index is gone, `secret-get` cross-checks a second store and
warns if it cannot verify. If a store returns a value whose fingerprint does not
match, it is **refused** (fail closed) — investigate a possible corruption or
tamper before trusting any copy.

To re-establish full redundancy after a lost store, just store the recovered
secret again — `secret-store` re-populates every store and re-verifies.

## Rotation

1. Mint or obtain the new value (e.g. `--generate`, or from the provider).
2. `secret-store <name> …` with the new value — this **overwrites in place** across
   all stores (1Password edits the existing item; the OS store updates; the backup
   is replaced) and re-verifies the new fingerprint.
3. Roll the credential at the provider / re-encrypt with the new key.
4. Record the rotation date. Suggested cadence: **rotate long-lived secrets at
   least every 90 days**, and immediately on any suspected exposure (a value that
   ever touched a chat, a log, a commit, or an unexpected process is compromised).

## Limits

- **macOS argv window:** `security add-generic-password` takes the value via `-w`,
  so the base64 payload is briefly visible in that one local, short-lived process's
  arguments. This matches the platform's only scriptable path; it is never logged.
  Linux (`secret-tool`, stdin) and Windows (in-process P/Invoke) avoid even that.
- **Windows Credential Manager blob** is limited to ~2560 bytes per generic
  credential; larger secrets fall back to the 1Password + on-disk copies (still
  redundant). Typical keys/tokens are far smaller.
- These scripts run on the **host** (they talk to host keychains), not in Docker —
  the one deliberate exception to the no-host-execution norm, since a container
  cannot reach the workstation's secret stores.
