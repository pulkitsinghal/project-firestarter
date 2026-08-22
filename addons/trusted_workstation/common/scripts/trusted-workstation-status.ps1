#requires -Version 5.1
[CmdletBinding()]
param([string]$Ledger)
$ErrorActionPreference = 'Stop'
$repositoryFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'trusted-workstation\repository.txt'
if (-not (Test-Path -LiteralPath $repositoryFile -PathType Leaf)) { 'BLOCKED repository configuration is missing'; exit 2 }
$expectedRepo = [IO.File]::ReadAllText($repositoryFile, [Text.Encoding]::ASCII).TrimEnd("`r", "`n")
if ($expectedRepo -notmatch '^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100}$') { 'BLOCKED repository configuration is invalid'; exit 2 }
if (($expectedRepo -split '/', 2)[1] -in @('.', '..')) { 'BLOCKED repository configuration is invalid'; exit 2 }
function Has-Control([string]$Value) { $Value -match '[\x00-\x1f\x7f-\x9f]' }
function Has-ReparseComponent([string]$Path) {
  $full = [IO.Path]::GetFullPath($Path); $rootPart = [IO.Path]::GetPathRoot($full)
  $cursor = $rootPart
  foreach ($part in ($full.Substring($rootPart.Length) -split '[\\/]' | Where-Object { $_ })) {
    $cursor = Join-Path $cursor $part
    $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $true }
  }
  return $false
}
if (-not $Ledger) { $Ledger = $env:TRUSTED_WORKSTATION_LEDGER }
if (-not $Ledger) { $Ledger = Join-Path $env:LOCALAPPDATA (Join-Path 'Firestarter\trusted-workstation' (($expectedRepo -replace '/', '--') + '\ledger.json')) }
if (Has-Control $Ledger -or $Ledger.Length -gt 2048) { 'BLOCKED ledger path is malformed'; exit 1 }
if (-not (Test-Path -LiteralPath $Ledger -PathType Leaf)) { 'NOT_ENROLLED ledger is missing'; exit 1 }
if (Has-ReparseComponent $Ledger) { 'BLOCKED ledger path must not contain a link or reparse point'; exit 1 }
$validator = Join-Path $PSScriptRoot 'trusted-workstation-ledger-validator.js'
$cscript = Join-Path $env:SystemRoot 'System32\cscript.exe'
if (-not (Test-Path -LiteralPath $cscript -PathType Leaf)) { 'BLOCKED Windows Script Host is unavailable'; exit 2 }
& $cscript //nologo $validator $Ledger $expectedRepo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
