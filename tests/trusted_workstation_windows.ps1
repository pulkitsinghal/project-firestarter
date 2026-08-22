#requires -Version 5.1
# Native Windows behavior gate. All writes are confined to one disposable fixture root.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceCommon = Join-Path $repoRoot 'addons\trusted_workstation\common'
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ("firestarter-trusted-workstation-" + [guid]::NewGuid().ToString('N'))
$utf8 = New-Object Text.UTF8Encoding($false)
$passed = 0

function Write-Fixture([string]$Name, [string]$Content) {
  $path = Join-Path $fixtureRoot $Name
  [IO.File]::WriteAllText($path, $Content, $utf8)
  return $path
}
function Invoke-Status([string]$Path) {
  $savedPreference = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $status -Ledger $Path 2>&1
  $code = $LASTEXITCODE
  $ErrorActionPreference = $savedPreference
  [pscustomobject]@{ Code = $code; Output = ($output -join "`n") }
}
function Assert-Case([string]$Name, [string]$Json, [bool]$Accept) {
  $path = Write-Fixture "$Name.json" $Json
  $before = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
  $result = Invoke-Status $path
  $after = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
  if (($result.Code -eq 0) -ne $Accept) { throw "$Name unexpected exit $($result.Code): $($result.Output)" }
  if ($before -ne $after) { throw "$Name mutated its ledger fixture" }
  if ($result.Output.Length -gt 512 -or $result.Output -match '[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]') {
    throw "$Name emitted unbounded or terminal-control output"
  }
  $script:passed += 1
}

$repo = 'Example-Org/sample-repo'
$base = '"schemaVersion":"1.0","repository":"' + $repo + '","clonePath":"C:\\synthetic\\clone","state":"blocked","checks":{},"updatedAt":"2026-08-22T00:00:00Z"'
$allChecks = '"cloneOwned":"pass","remoteMatch":"pass","hooksInstalled":"pass","canaryCiphertext":"pass","canaryPlaintext":"pass"'
$machine = '"platform":"windows","tailscaleNodeId":"node-synthetic","tailscaleDnsName":"synthetic.tailnet.ts.net"'
$fingerprint = ('a' * 64); $revision = ('b' * 40)

New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
try {
  $runtime = Join-Path $fixtureRoot 'runtime'
  Copy-Item -LiteralPath $sourceCommon -Destination $runtime -Recurse
  [IO.File]::WriteAllText((Join-Path $runtime 'trusted-workstation\repository.txt'), "$repo`n", $utf8)
  $scripts = Join-Path $runtime 'scripts'
  $status = Join-Path $scripts 'trusted-workstation-status.ps1'
  $doctor = Join-Path $scripts 'trusted-workstation-doctor.ps1'
  Assert-Case valid_blocked ("{" + $base + "}") $true
  Assert-Case malformed '{"schemaVersion":' $false
  Assert-Case duplicate ("{" + $base + ',"state":"cloned"}') $false
  Assert-Case unknown ("{" + $base + ',"extra":true}') $false
  Assert-Case wrong_type ("{" + $base.Replace('"checks":{}', '"checks":[]') + "}") $false
  Assert-Case control_char ('{"schemaVersion":"1.0","repository":"' + $repo + '","clonePath":"bad\u001bpath","state":"blocked","checks":{},"updatedAt":"2026-08-22T00:00:00Z"}') $false
  Assert-Case verified_missing_evidence ('{"schemaVersion":"1.0","repository":"' + $repo + '","clonePath":"C:\\synthetic","state":"verified","checks":{' + $allChecks + '},"updatedAt":"2026-08-22T00:00:00Z"}') $false
  Assert-Case verified_valid ('{"schemaVersion":"1.0","repository":"' + $repo + '","clonePath":"C:\\synthetic","state":"verified","checks":{' + $allChecks + '},"machine":{' + $machine + '},"revision":"' + $revision + '","keyFingerprint":"' + $fingerprint + '","updatedAt":"2026-08-22T00:00:00Z"}') $true
  Assert-Case sync_missing_mutagen ('{"schemaVersion":"1.0","repository":"' + $repo + '","clonePath":"C:\\synthetic","state":"sync-enabled","checks":{' + $allChecks + '},"machine":{' + $machine + '},"revision":"' + $revision + '","keyFingerprint":"' + $fingerprint + '","updatedAt":"2026-08-22T00:00:00Z"}') $false
  Assert-Case sync_valid ('{"schemaVersion":"1.0","repository":"' + $repo + '","clonePath":"C:\\synthetic","state":"sync-enabled","checks":{' + $allChecks + '},"machine":{' + $machine + '},"revision":"' + $revision + '","keyFingerprint":"' + $fingerprint + '","mutagen":{"enabled":true,"sessionName":"synthetic","mode":"one-way-safe","exclusions":[".git",".git/**",".git-crypt/**","*.key","*.git-crypt.key"]},"updatedAt":"2026-08-22T00:00:00Z"}') $true

  $corpus = Join-Path $repoRoot 'tests\fixtures\trusted_workstation_ledgers'
  foreach ($entry in @(@{ Directory = 'accepted'; Accept = $true }, @{ Directory = 'rejected'; Accept = $false })) {
    Get-ChildItem -LiteralPath (Join-Path $corpus $entry.Directory) -Filter '*.json' | ForEach-Object {
      Assert-Case ("corpus_" + $entry.Directory + "_" + $_.BaseName) ([IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8)) $entry.Accept
    }
  }
  $repositoryFile = Join-Path $runtime 'trusted-workstation\repository.txt'
  [IO.File]::WriteAllText($repositoryFile, "Example-Org/.`n", $utf8)
  $invalidRepository = Invoke-Status (Write-Fixture 'invalid-repository-ledger.json' ("{" + $base + "}"))
  if ($invalidRepository.Code -ne 2 -or $invalidRepository.Output -notmatch 'repository configuration is invalid') {
    throw "special repository segment was not rejected: $($invalidRepository.Output)"
  }
  [IO.File]::WriteAllText($repositoryFile, "$repo`n", $utf8)
  $passed += 1

  $targetDir = Join-Path $fixtureRoot 'target'; New-Item -ItemType Directory -Path $targetDir | Out-Null
  $targetLedger = Join-Path $targetDir 'ledger.json'; [IO.File]::WriteAllText($targetLedger, "{" + $base + "}", $utf8)
  $junction = Join-Path $fixtureRoot 'linked-parent'
  New-Item -ItemType Junction -Path $junction -Target $targetDir | Out-Null
  $linkedResult = Invoke-Status (Join-Path $junction 'ledger.json')
  if ($linkedResult.Code -eq 0 -or $linkedResult.Output -notmatch 'reparse') { throw 'linked ledger parent was not rejected' }
  $passed += 1

  $clone = Join-Path $fixtureRoot 'clone'; New-Item -ItemType Directory -Path $clone | Out-Null
  & git init $clone 2>&1 | Out-Null
  & git -C $clone remote add origin "https://github.com/$repo.git"
  $fakeBin = Join-Path $fixtureRoot 'fake-bin'; New-Item -ItemType Directory -Path $fakeBin | Out-Null
  foreach ($tool in @('git-crypt', 'op', 'tailscale')) { [IO.File]::WriteAllText((Join-Path $fakeBin "$tool.cmd"), "@exit /b 99`r`n", $utf8) }
  $savedPath = $env:PATH; $env:PATH = "$fakeBin;$savedPath"
  Push-Location $clone
  try {
    $doctorOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $doctor 2>&1
    if ($LASTEXITCODE -ne 0) { throw "independent clone doctor failed: $($doctorOutput -join ' ')" }
    $externalGit = Join-Path $fixtureRoot 'external-git'; Move-Item -LiteralPath (Join-Path $clone '.git') -Destination $externalGit
    $gitJunction = Join-Path $clone '.git'; New-Item -ItemType Junction -Path $gitJunction -Target $externalGit | Out-Null
    $linkedDoctor = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $doctor 2>&1
    if ($LASTEXITCODE -eq 0 -or ($linkedDoctor -join ' ') -notmatch 'linked, external, or shared') { throw 'linked Git metadata was not rejected' }
    [IO.Directory]::Delete($gitJunction)
    $passed += 2
  } finally { Pop-Location; $env:PATH = $savedPath }
} finally {
  $junction = Join-Path $fixtureRoot 'linked-parent'
  if (Test-Path -LiteralPath $junction) { [IO.Directory]::Delete($junction) }
  $gitJunction = Join-Path (Join-Path $fixtureRoot 'clone') '.git'
  if (Test-Path -LiteralPath $gitJunction) {
    $gitItem = Get-Item -LiteralPath $gitJunction -Force
    if ($gitItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($gitJunction) }
  }
  if (Test-Path -LiteralPath $fixtureRoot) { Remove-Item -LiteralPath $fixtureRoot -Recurse -Force }
}
"Windows trusted-workstation behavior: PASS ($passed cases)"
