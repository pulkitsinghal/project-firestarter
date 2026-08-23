# Trusted workstation: read-only phase

This optional component establishes the contract for enrolling independent
Windows and macOS Git clones as trusted workstations. The current phase is a
doctor only: it reports readiness and reads an existing local status ledger.

It does **not** retrieve a git-crypt key, contact or configure Tailscale, change
SSH/firewall/services, install hooks, create a Mutagen session, or write an
enrollment ledger. Those capabilities remain forbidden by
`trusted-workstation/policy.json` until separately implemented and reviewed.

Run the platform doctor from inside an independent clone:

```bash
./scripts/trusted-workstation-doctor.sh
```

```powershell
.\scripts\trusted-workstation-doctor.ps1
```

Read a pre-existing ledger with `trusted-workstation-status` and `--ledger`
(shell) or `-Ledger` (PowerShell). The commands never repair or update it.
Windows uses the built-in Windows Script Host; macOS uses its built-in JXA
runtime. Both execute the same strict validator, reject duplicate/unknown keys,
enforce state-dependent evidence, reject terminal control characters and linked
ledger paths, cap input at 64 KiB, and emit only a bounded normalized summary.

The future design keeps Git authoritative, uses Tailscale SSH only between
explicitly trusted devices, retrieves the git-crypt key through 1Password into
an ephemeral file, verifies a synthetic ciphertext canary, installs only
repository-local hooks, and keeps Mutagen optional and disabled by default.
