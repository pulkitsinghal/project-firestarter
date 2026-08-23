#requires -Version 5.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repositoryFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'trusted-workstation\repository.txt'
if (-not (Test-Path -LiteralPath $repositoryFile -PathType Leaf)) { 'BLOCKED repository configuration is missing'; exit 2 }
$repositoryBytes = [IO.File]::ReadAllBytes($repositoryFile)
if ($repositoryBytes.Length -gt 142) { 'BLOCKED repository configuration is invalid'; exit 2 }
$contentLength = $repositoryBytes.Length
if ($contentLength -gt 0 -and $repositoryBytes[$contentLength - 1] -eq 10) {
  $contentLength -= 1
  if ($contentLength -gt 0 -and $repositoryBytes[$contentLength - 1] -eq 13) { $contentLength -= 1 }
}
for ($index = 0; $index -lt $contentLength; $index++) {
  if ($repositoryBytes[$index] -lt 32 -or $repositoryBytes[$index] -gt 126) { 'BLOCKED repository configuration is invalid'; exit 2 }
}
$expectedRepo = [Text.Encoding]::ASCII.GetString($repositoryBytes, 0, $contentLength)
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

function Test-RemoteUrls([string[]]$Arguments) {
  $lines = @(& git remote get-url @Arguments origin 2>$null)
  if ($LASTEXITCODE -ne 0 -or $lines.Count -eq 0 -or ($lines -join "`n").Length -gt 8192) { return $false }
  foreach ($line in $lines) {
    $remote = [string]$line
    if (-not $remote -or (Has-Control $remote) -or $remote.Length -gt 2048) { return $false }
    if ($remote -match '^git@github\.com:') { $normalized = $remote -replace '^git@github\.com:', 'https://github.com/' }
    elseif ($remote -match '^https://github\.com/') { $normalized = $remote }
    else { return $false }
    $normalized = $normalized -replace '\.git$', ''
    if ($normalized -ine "https://github.com/$expectedRepo") { return $false }
  }
  return $true
}
if ((Test-RemoteUrls -Arguments @('--all')) -and (Test-RemoteUrls -Arguments @('--push', '--all'))) {
  Report PASS 'origin fetch and push URLs match the configured repository'
} else { Report BLOCKED 'origin fetch or push URL does not match the configured repository'; $failed = $true }

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
