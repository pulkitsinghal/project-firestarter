#requires -Version 5.1
# git-crypt-key.ps1 — store / restore a repository's git-crypt symmetric key in
# the secret vault under the conventional name "git-crypt: <repo>". Windows.
#
# The Windows counterpart of git-crypt-key.sh: same "git-crypt: <repo>" naming
# and 1Password + OS-store redundancy, now with a DPAPI-protected on-disk backup,
# fingerprint verification, and cross-platform restore — via secret-store/get.
#
#   .\git-crypt-key.ps1 store   [repo] [-Key <path>]
#   .\git-crypt-key.ps1 restore [repo] [-Out <path>] [-Unlock]
#
# <repo> defaults to the basename of the current git worktree. The key is
# exported to an ACL-locked temp file, stored, then shredded — never printed,
# never passed as an argument.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\secret-vault-lib.ps1"

# git-crypt keys historically live under the "git-crypt" OS account.
$GcAccount = 'git-crypt'

function Show-Usage {
  @'
usage: git-crypt-key.ps1 <store|restore> [repo] [options]

  store [repo] [-Key <path>]         Store the repo's git-crypt key in the vault.
  restore [repo] [-Out <path>] [-Unlock]
                                     Fetch the key; -Unlock runs `git crypt unlock`.

  repo          Repository label (default: basename of the git worktree root).
  -OpVault <v>  1Password vault to use.
  -h, -Help     Show this help.

The vault item is named "git-crypt: <repo>".
'@ | Write-Host
}

if ($args.Count -lt 1) { Show-Usage; exit 2 }
$Cmd = [string]$args[0]
$Repo = $null; $KeyPath = $null; $OutPath = $null; $DoUnlock = $false
$i = 1
while ($i -lt $args.Count) {
  $a = [string]$args[$i]
  switch -Regex ($a) {
    '^(-h|--help|-Help)$'   { Show-Usage; exit 0 }
    '^(--key|-Key)$'        { $KeyPath = [string]$args[$i+1]; $i += 2; continue }
    '^(--out|-Out)$'        { $OutPath = [string]$args[$i+1]; $i += 2; continue }
    '^(--unlock|-Unlock)$'  { $DoUnlock = $true; $i += 1; continue }
    '^(--op-vault|-OpVault)$' { $env:SECRET_VAULT_OP_VAULT = [string]$args[$i+1]; $i += 2; continue }
    '^-' { Sv-Info "unknown option: $a"; Show-Usage; exit 2 }
    default { if (-not $Repo) { $Repo = $a; $i += 1 } else { Sv-Info "unexpected argument: $a"; Show-Usage; exit 2 } }
  }
}

function Git-Toplevel { try { (& git rev-parse --show-toplevel 2>$null).Trim() } catch { '' } }
if (-not $Repo) { $top = Git-Toplevel; if ($top) { $Repo = Split-Path -Leaf $top } }
if (-not $Repo) { Sv-Die "no repo given and not inside a git worktree" }
$Name = "git-crypt: $Repo"

if (-not (Get-Command git-crypt -ErrorAction SilentlyContinue)) { Sv-Die "git-crypt is not installed" }

switch ($Cmd) {
  'store' {
    $tmp = $null
    try {
      if ($KeyPath) {
        if (-not (Test-Path $KeyPath)) { Sv-Die "no such key file: $KeyPath" }
        $src = $KeyPath
      } else {
        $tmp = Sv-NewTemp
        & git crypt export-key $tmp 2>$null 1>$null
        if ($LASTEXITCODE -ne 0) { Sv-Die "git crypt export-key failed (is this an unlocked git-crypt repo?)" }
        $src = $tmp
      }
      & "$PSScriptRoot\secret-store.ps1" $Name -File $src -OsAccount $GcAccount
    } finally { if ($tmp) { Sv-Shred $tmp } }
  }
  'restore' {
    if ($DoUnlock -and -not $OutPath) {
      $tmp = Sv-NewTemp
      try {
        & "$PSScriptRoot\secret-get.ps1" $Name -File $tmp -OsAccount $GcAccount | Out-Null
        & git crypt unlock $tmp; if ($LASTEXITCODE -ne 0) { Sv-Die "git crypt unlock failed" }
        Sv-Info "+ unlocked $(Git-Toplevel) with the key for '$Repo'"
      } finally { Sv-Shred $tmp }
    } else {
      if (-not $OutPath) { $OutPath = ".\git-crypt-$(Sv-Slug $Repo).key" }
      & "$PSScriptRoot\secret-get.ps1" $Name -File $OutPath -OsAccount $GcAccount | Out-Null
      Sv-Info "+ wrote the git-crypt key for '$Repo' to $OutPath (ACL-locked)"
      if ($DoUnlock) { & git crypt unlock $OutPath; if ($LASTEXITCODE -ne 0) { Sv-Die "git crypt unlock failed" } }
    }
  }
  default { Sv-Info "unknown command: $Cmd"; Show-Usage; exit 2 }
}
