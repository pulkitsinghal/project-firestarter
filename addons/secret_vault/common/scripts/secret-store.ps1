#requires -Version 5.1
# secret-store.ps1 — store a NAMED secret redundantly across durable stores and
# verify every copy by sha256 fingerprint (defense-in-redundancy). Windows.
#
# The secret VALUE is never passed as an argument. Provide it via the pipeline
# (default), a file, or ask the tool to generate one:
#
#   op read 'op://Private/some-api/credential' | .\secret-store.ps1 MY_API_KEY
#   .\secret-store.ps1 MY_API_KEY -File .\key.bin
#   .\secret-store.ps1 MY_API_KEY -Generate 32
#
# Writes to (all available; >=2 durable copies required):
#   1. 1Password           — op document titled <name>            (needs op, signed in)
#   2. Credential Manager  — Windows generic credential           (raw bytes)
#   3. On-disk backup      — %USERPROFILE%\.secret-vault\backups   (DPAPI at rest)
# then reads each back, hashes it, and ASSERTS every fingerprint matches. Prints
# ONLY the fingerprint + per-store status — never the secret value.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\secret-vault-lib.ps1"

function Show-Usage {
  @'
usage: secret-store.ps1 <name> [input] [options]

  <name>                Logical secret name (e.g. MY_API_KEY, "git-crypt: repo").

input (choose one; default: pipeline / stdin):
  (pipeline)            Read the raw secret bytes from the pipeline / stdin.
  -File <path>          Read the raw secret bytes from a file.
  -Generate [BYTES]     Generate BYTES (default 32) of random bytes as the secret.

options:
  -OsAccount <acct>     Credential Manager account label (default: secret-vault).
  -OpVault <vault>      1Password vault to store the document in.
  -NoOp                 Skip the 1Password copy.
  -NoOs                 Skip the Credential Manager copy.
  -h, -Help             Show this help.

Never pass the secret value as an argument.
'@ | Write-Host
}

# ── Parse args ────────────────────────────────────────────────────────────────
$Name = $null; $InputMode = 'stdin'; $InputFile = $null; $GenBytes = 32
$UseOp = $true; $UseOs = $true
$i = 0
while ($i -lt $args.Count) {
  $a = [string]$args[$i]
  switch -Regex ($a) {
    '^(-h|--help|-Help)$'    { Show-Usage; exit 0 }
    '^(--file|-File)$'       { $InputMode = 'file'; $InputFile = [string]$args[$i+1]; $i += 2; continue }
    '^(--generate|-Generate)$' {
      $InputMode = 'generate'
      if (($i+1) -lt $args.Count -and [string]$args[$i+1] -match '^\d+$') { $GenBytes = [int]$args[$i+1]; $i += 2 } else { $i += 1 }
      continue
    }
    '^(--os-account|-OsAccount)$' { $script:SvOsAccount = [string]$args[$i+1]; $i += 2; continue }
    '^(--op-vault|-OpVault)$'     { $script:SvOpVault   = [string]$args[$i+1]; $i += 2; continue }
    '^(--no-op|-NoOp)$'           { $UseOp = $false; $i += 1; continue }
    '^(--no-os|-NoOs)$'           { $UseOs = $false; $i += 1; continue }
    '^-'                          { Sv-Info "unknown option: $a"; Show-Usage; exit 2 }
    default {
      if (-not $Name) { $Name = $a; $i += 1 } else { Sv-Info "unexpected argument: $a"; Show-Usage; exit 2 }
    }
  }
}
if (-not $Name) { Show-Usage; exit 2 }

# ── Acquire raw bytes ─────────────────────────────────────────────────────────
[byte[]]$Raw = $null
switch ($InputMode) {
  'file' {
    if (-not (Test-Path $InputFile)) { Sv-Die "no such file: $InputFile" }
    $Raw = [System.IO.File]::ReadAllBytes($InputFile)
  }
  'generate' {
    $Raw = New-Object byte[] $GenBytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($Raw)
  }
  'stdin' {
    if (-not [Console]::IsInputRedirected) { Sv-Die "no secret on the pipeline (pipe it in, or use -File / -Generate)" }
    $stdin = [Console]::OpenStandardInput()
    $ms = New-Object System.IO.MemoryStream
    $stdin.CopyTo($ms)
    $Raw = $ms.ToArray()
    $ms.Dispose()
  }
}
if ($null -eq $Raw -or $Raw.Length -eq 0) { Sv-Die "the secret is empty; nothing to store" }

$Fp = Sv-Sha256Hex $Raw

# raw temp file for the stores that consume a path (op)
$RawTmp = Sv-NewTemp
[System.IO.File]::WriteAllBytes($RawTmp, $Raw)

$Durable = 0
$Lines = New-Object System.Collections.Generic.List[string]

function Verify-Store([scriptblock]$getter) {   # getter -> byte[] or $null
  $b = & $getter
  if ($null -eq $b) { return $false }
  return ((Sv-Sha256Hex $b) -eq $Fp)
}

try {
  # 1Password
  if ($UseOp -and (Sv-OpAvailable)) {
    if ((Sv-OpSet $Name $RawTmp) -and (Verify-Store {
          $o = Sv-NewTemp; try { if (Sv-OpGet $Name $o) { [System.IO.File]::ReadAllBytes($o) } else { $null } } finally { Sv-Shred $o } })) {
      $Lines.Add('  1Password              : ok'); $Durable++
    } else { $Lines.Add('  1Password              : FAILED (stored or verified badly)') }
  } elseif ($UseOp) {
    $Lines.Add('  1Password              : skipped (op not installed / not signed in)')
  } else { $Lines.Add('  1Password              : skipped (-NoOp)') }

  # Credential Manager
  if ($UseOs) {
    Sv-CredSet $Name $Raw
    if (Verify-Store { Sv-CredGet $Name }) {
      $Lines.Add('  Credential Manager     : ok'); $Durable++
    } else { $Lines.Add('  Credential Manager     : FAILED (stored or verified badly)') }
  } else { $Lines.Add('  Credential Manager     : skipped (-NoOs)') }

  # On-disk backup (DPAPI at rest) — the recovery floor
  Sv-BackupSet $Name $Raw
  if (Verify-Store { Sv-BackupGet $Name }) {
    $Lines.Add("  backup ($(Sv-BackupPath $Name)): ok"); $Durable++
  } else { $Lines.Add("  backup ($(Sv-BackupPath $Name)): FAILED") }

  Sv-IndexSet $Name $Fp
}
finally {
  Sv-Shred $RawTmp
  # Zero the in-memory copy.
  if ($Raw) { [Array]::Clear($Raw, 0, $Raw.Length) }
}

Write-Host ''
Write-Host "secret: $Name"
Write-Host "fingerprint (sha256): $Fp"
$Lines | ForEach-Object { Write-Host $_ }

if ($Durable -lt 2) {
  Sv-Die "only $Durable durable copy stored — need at least 2 (redundancy floor). Secret is NOT safely stored."
}
Write-Host ''
Write-Host ("+ {0} durable copies, all fingerprints match ({1}...)" -f $Durable, $Fp.Substring(0, 12))
