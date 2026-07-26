#requires -Version 5.1
# secret-get.ps1 — retrieve a named secret for RUNTIME use, with primary-store
# fallback and fingerprint verification. Windows.
#
# Prefer streaming straight into the consuming command so the value never lands
# in a file or lingers in the environment beyond the child that needs it:
#
#   .\secret-get.ps1 MY_API_KEY -Exec API_KEY -- myserver.exe --port 8080
#       ↑ fetches + verifies, sets $env:API_KEY for the child only, runs it,
#         then clears the variable. The value never appears in argv.
#
# Other sinks:
#   .\secret-get.ps1 MY_API_KEY                 # stream raw bytes to stdout (pipe)
#   .\secret-get.ps1 MY_API_KEY -File out.bin   # write to an ACL-locked file (binary-safe)
#
# Source order for -Source auto (default): 1Password -> Credential Manager ->
# backup; first hit wins. The value is hashed and checked against the recorded
# fingerprint (or a second store) before use.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\secret-vault-lib.ps1"

function Show-Usage {
  @'
usage: secret-get.ps1 <name> [sink] [options]

  <name>                Logical secret name used at store time.

sink (choose one; default: stream to stdout):
  -Exec <ENVVAR> -- cmd [args...]   Set $env:ENVVAR for the child only, then run
                                    cmd. The value is never placed in argv.
  -File <path>                      Write raw bytes to an ACL-locked file.
  -Stdout                           Stream raw bytes to stdout (explicit default).

options:
  -Source <auto|op|os|backup>   Which store to read (default: auto, with fallback).
  -OsAccount <acct>             Credential Manager account label (default: secret-vault).
  -OpVault <vault>              1Password vault to read from.
  -NoVerify                     Skip the fingerprint check (not recommended).
  -h, -Help                     Show this help.
'@ | Write-Host
}

$Name = $null; $Sink = 'stdout'; $OutFile = $null; $ExecEnv = $null; $ExecCmd = @()
$Source = 'auto'; $Verify = $true
$i = 0
while ($i -lt $args.Count) {
  $a = [string]$args[$i]
  switch -Regex ($a) {
    '^(-h|--help|-Help)$' { Show-Usage; exit 0 }
    '^(--stdout|-Stdout)$' { $Sink = 'stdout'; $i += 1; continue }
    '^(--file|-File)$'     { $Sink = 'file'; $OutFile = [string]$args[$i+1]; $i += 2; continue }
    '^(--exec|-Exec)$' {
      $Sink = 'exec'; $ExecEnv = [string]$args[$i+1]; $i += 2
      if ([string]$args[$i] -ne '--') { Sv-Info '-Exec <ENVVAR> must be followed by -- <cmd>'; Show-Usage; exit 2 }
      $i += 1
      $ExecCmd = @(); while ($i -lt $args.Count) { $ExecCmd += [string]$args[$i]; $i += 1 }
      break
    }
    '^(--source|-Source)$'        { $Source = [string]$args[$i+1]; $i += 2; continue }
    '^(--os-account|-OsAccount)$' { $script:SvOsAccount = [string]$args[$i+1]; $i += 2; continue }
    '^(--op-vault|-OpVault)$'     { $script:SvOpVault   = [string]$args[$i+1]; $i += 2; continue }
    '^(--no-verify|-NoVerify)$'   { $Verify = $false; $i += 1; continue }
    '^-' { Sv-Info "unknown option: $a"; Show-Usage; exit 2 }
    default {
      if (-not $Name) { $Name = $a; $i += 1 } else { Sv-Info "unexpected argument: $a"; Show-Usage; exit 2 }
    }
  }
}
if (-not $Name) { Show-Usage; exit 2 }
if ($Sink -eq 'exec' -and (-not $ExecEnv -or $ExecCmd.Count -eq 0)) { Sv-Info '-Exec needs <ENVVAR> -- <cmd>'; Show-Usage; exit 2 }
if ($Sink -eq 'file' -and -not $OutFile) { Show-Usage; exit 2 }

# ── Fetch (with fallback) ─────────────────────────────────────────────────────
$From = $null
[byte[]]$Bytes = $null

function Try-Op {
  if (-not (Sv-OpAvailable)) { return $false }
  $o = Sv-NewTemp
  try { if (Sv-OpGet $Name $o) { $script:Bytes = [System.IO.File]::ReadAllBytes($o); $script:From = '1Password'; return $true } return $false }
  finally { Sv-Shred $o }
}
function Try-Os      { $b = Sv-CredGet $Name;   if ($null -ne $b) { $script:Bytes = $b; $script:From = (Sv-OsStoreLabel); return $true } return $false }
function Try-Backup  { $b = Sv-BackupGet $Name; if ($null -ne $b) { $script:Bytes = $b; $script:From = 'backup'; return $true } return $false }

switch ($Source) {
  'op'     { if (-not (Try-Op))     { Sv-Die "not found in 1Password" } }
  'os'     { if (-not (Try-Os))     { Sv-Die "not found in Credential Manager" } }
  'backup' { if (-not (Try-Backup)) { Sv-Die "not found in the on-disk backup" } }
  'auto'   { if (-not ((Try-Op) -or (Try-Os) -or (Try-Backup))) { Sv-Die "secret '$Name' not found in any store" } }
  default  { Sv-Die "unknown -Source '$Source' (use auto|op|os|backup)" }
}

# ── Verify fingerprint ────────────────────────────────────────────────────────
if ($Verify) {
  $got = Sv-Sha256Hex $Bytes
  $want = Sv-IndexGet $Name
  if ($want) {
    if ($got -ne $want) { Sv-Die "fingerprint mismatch (store '$From' returned $got, expected $want) - refusing to use it" }
  } else {
    $alt = $null; $other = $null
    if ($From -ne 'backup') { $alt = Sv-BackupGet $Name; if ($null -ne $alt) { $other = 'backup' } }
    if ($null -eq $alt -and $From -ne (Sv-OsStoreLabel)) { $alt = Sv-CredGet $Name; if ($null -ne $alt) { $other = (Sv-OsStoreLabel) } }
    if ($null -ne $alt) {
      if ((Sv-Sha256Hex $alt) -ne $got) { Sv-Die "cross-store fingerprint mismatch between '$From' and '$other'" }
    } else {
      Sv-Info "! no recorded fingerprint and no second store to cross-check '$Name' (proceeding unverified)"
    }
  }
}

Sv-Info "-> retrieved '$Name' from $From"

# ── Deliver ───────────────────────────────────────────────────────────────────
switch ($Sink) {
  'stdout' {
    $out = [Console]::OpenStandardOutput()
    $out.Write($Bytes, 0, $Bytes.Length); $out.Flush()
  }
  'file' {
    [System.IO.File]::WriteAllBytes($OutFile, $Bytes)
    Sv-LockAcl $OutFile
    Sv-Info "-> wrote $OutFile (ACL-locked)"
  }
  'exec' {
    $val = [System.Text.Encoding]::UTF8.GetString($Bytes)
    $cmd = $ExecCmd[0]; $rest = @(); if ($ExecCmd.Count -gt 1) { $rest = $ExecCmd[1..($ExecCmd.Count-1)] }
    try {
      Set-Item -Path "Env:$ExecEnv" -Value $val
      & $cmd @rest
      exit $LASTEXITCODE
    } finally {
      if (Test-Path "Env:$ExecEnv") { Remove-Item -Path "Env:$ExecEnv" -ErrorAction SilentlyContinue }
      if ($Bytes) { [Array]::Clear($Bytes, 0, $Bytes.Length) }
    }
  }
}
