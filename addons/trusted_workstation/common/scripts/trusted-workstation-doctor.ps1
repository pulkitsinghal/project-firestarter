#requires -Version 5.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repositoryFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'trusted-workstation\repository.txt'
if (-not (Test-Path -LiteralPath $repositoryFile -PathType Leaf)) { 'BLOCKED repository configuration is missing'; exit 2 }
$expectedRepo = [IO.File]::ReadAllText($repositoryFile, [Text.Encoding]::ASCII).TrimEnd("`r", "`n")
if ($expectedRepo -notmatch '^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100}$') { 'BLOCKED repository configuration is invalid'; exit 2 }
if (($expectedRepo -split '/', 2)[1] -in @('.', '..')) { 'BLOCKED repository configuration is invalid'; exit 2 }
$failed = $false
function Report([string]$State, [string]$Message) { '{0,-12} {1}' -f $State, $Message }
function Has-Command([string]$Name) { $null -ne (Get-Command $Name -ErrorAction SilentlyContinue) }
function Has-ReparseComponent([string]$Path) {
  $full = [IO.Path]::GetFullPath($Path)
  $rootPart = [IO.Path]::GetPathRoot($full)
  $relative = $full.Substring($rootPart.Length)
  $cursor = $rootPart
  foreach ($part in ($relative -split '[\\/]' | Where-Object { $_ })) {
    $cursor = Join-Path $cursor $part
    $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $true }
  }
  return $false
}
function Has-Control([string]$Value) { $Value -match '[\x00-\x1f\x7f-\x9f]' }

if (-not (Has-Command 'git')) { Report BLOCKED 'git is not available'; exit 1 }
$root = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $root) { Report BLOCKED 'run this command inside the repository clone'; exit 1 }
$root = $root.Trim()
if (Has-Control $root) { Report BLOCKED 'clone path contains control characters'; exit 1 }
$root = [IO.Path]::GetFullPath($root)
$gitDirRaw = (& git rev-parse --absolute-git-dir 2>$null).Trim()
$commonRaw = (& git rev-parse --git-common-dir 2>$null).Trim()
$gitDir = [IO.Path]::GetFullPath($gitDirRaw)
$commonDir = if ([IO.Path]::IsPathRooted($commonRaw)) { [IO.Path]::GetFullPath($commonRaw) } else { [IO.Path]::GetFullPath((Join-Path $root $commonRaw)) }
$ownedGit = Join-Path $root '.git'
$currentPath = [IO.Path]::GetFullPath((Get-Location).Path)
if ($gitDir -ieq $ownedGit -and $commonDir -ieq $ownedGit -and
    (Test-Path -LiteralPath $gitDir -PathType Container) -and
    -not (Has-ReparseComponent $currentPath) -and
    -not (Has-ReparseComponent $root) -and -not (Has-ReparseComponent $gitDir)) {
  Report PASS 'independent clone metadata is canonical and clone-owned'
} else { Report BLOCKED 'clone root or Git metadata is linked, external, or shared'; $failed = $true }

$remote = (& git remote get-url origin 2>$null).Trim()
if (Has-Control $remote -or $remote.Length -gt 2048) { Report BLOCKED 'origin is malformed'; exit 1 }
$normalized = $remote -replace '^git@github.com:', 'https://github.com/' -replace '\.git$', ''
if ($normalized -ieq "https://github.com/$expectedRepo") { Report PASS 'origin matches the configured repository' }
else { Report BLOCKED 'origin does not match the configured repository'; $failed = $true }

foreach ($tool in @('git-crypt', 'op', 'tailscale')) {
  if (Has-Command $tool) { Report PASS "$tool is available (not invoked)" }
  else { Report BLOCKED "$tool is not available"; $failed = $true }
}
if (Has-Command 'mutagen') { Report OPTIONAL 'mutagen is available (not invoked)' }
else { Report OPTIONAL 'mutagen is absent; synchronization stays disabled' }
$hooks = (& git config --local --get core.hooksPath 2>$null)
if ($hooks -eq '.githooks') { Report PASS 'repository-local hooks path is active' }
else { Report INFO 'repository-local hooks are not installed; phase 1 will not install them' }
if ($failed) { exit 1 }
