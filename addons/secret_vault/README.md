# `secret_vault` add-on (contributor notes)

> This file documents the add-on for **firestarter maintainers**. It lives above
> `common/`, so the generator does **not** stamp it into projects. The
> user-facing docs are `common/docs/SECRET_VAULT.md` (concept + usage + recovery
> + rotation) and `common/docs/SECRETS.md` (the house contract), which *do* stamp
> into `<project>/docs/`.

## What it is

A **stack-agnostic** add-on that lifts an ad-hoc, macOS-only `git-crypt-key-store`
pattern into a portable, generic secret tool. Concept: **defense-in-redundancy +
sha256 fingerprint integrity** — every secret is stored in several durable stores
at once and cross-verified, and retrieved by streaming straight into the consumer.

## Layout (all under `common/`, stamped to `<project>/`)

```
common/scripts/
  secret-vault-lib.sh    POSIX helpers: op + OS store (macOS Keychain / Linux
                         secret-service) + on-disk backup + sha256 (sourced)
  secret-vault-lib.ps1   Windows helpers: op + Credential Manager (advapi32
                         P/Invoke) + DPAPI backup + sha256 (dot-sourced)
  secret-store.{sh,ps1}  store a named secret to every store + verify fingerprint
  secret-get.{sh,ps1}    retrieve for runtime use (--exec/--file/stdout) + verify
  git-crypt-key.{sh,ps1} convenience wrapper: store/restore "git-crypt: <repo>"
common/docs/
  SECRET_VAULT.md        concept, platform matrix, usage, recovery, rotation
  SECRETS.md             the secrets house contract (wired into AGENTS.md)
```

## Platform mechanisms (all real, dependency-light)

| | macOS | Linux | Windows |
|-|-------|-------|---------|
| password mgr | `op` | `op` | `op` |
| OS store | Keychain (`security`) | secret-service (`secret-tool`) | Credential Manager (advapi32 `CredWrite`/`CredRead`, no PS module) |
| backup at rest | `0600` file | `0600` file | DPAPI (`ProtectedData`) + `icacls` |

## Design notes / gotchas

- **No secret in argv.** Values arrive via stdin / `--file` / `--generate`; the OS
  store holds base64 (POSIX) or raw bytes (CredMan) so binary keys round-trip.
- **Fingerprint index** (`~/.secret-vault/index/<slug>.sha256`) is non-secret and
  lets `secret-get` verify a single-store read; a mismatch is refused (fail closed).
- **bash 3.2 safe** (macOS system bash): empty-array expansion uses the
  `${arr[@]+"${arr[@]}"}` guard so `set -u` doesn't trip.
- **PowerShell:** `Add-Type -MemberDefinition` already injects
  `using System.Runtime.InteropServices;` — do **not** pass `-UsingNamespace` for
  it (CS0105). Empty-array splats are wrapped `@(...)` for StrictMode.
- **Runs on the host**, not in Docker (it talks to host keychains) — the one
  deliberate exception to the no-host-execution norm.

## Verify

`bash -n` every `.sh` (also under `/bin/bash` 3.2); parse every `.ps1` with
`[System.Management.Automation.Language.Parser]::ParseFile`. A stamped-output leak
grep is covered by the repo's `Verify before you commit` step in `AGENTS.md`.
