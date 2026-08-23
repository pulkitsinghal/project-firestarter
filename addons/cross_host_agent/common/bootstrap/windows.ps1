<#
.SYNOPSIS
  Open one scoped, tailnet-only, key-authenticated SSH channel on this Windows host.

.DESCRIPTION
  Written for Windows PowerShell 5.1. Must run elevated. Idempotent.

  It verifies by connecting to itself at the end rather than reporting success because no
  command threw, which is the failure mode that cost an afternoon: the capability
  installs, the service is created, a firewall rule is added, every line "succeeds", and
  the port is still closed from the tailnet because the rule landed on the wrong profile.

.PARAMETER PublicKey
  The public key of the machine that will connect. Required. Password authentication is
  never enabled by this script.

.PARAMETER TailnetOnly
  Scope the firewall rule to the Tailscale interface only. On by default, and turning it
  off is a deliberate act.

.EXAMPLE
  .\windows.ps1 -PublicKey "ssh-ed25519 AAAA... agent@macbook-pro"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PublicKey,
    [bool]$TailnetOnly = $true,
    [string]$RuleName = "agent-host-ssh"
)

$ErrorActionPreference = 'Stop'
function Ok   { param($m) Write-Host "  [ok]   $m" -ForegroundColor Green }
function Warn { param($m) Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Bad  { param($m) Write-Host "  [stop] $m" -ForegroundColor Red }
function Head { param($m) Write-Host "`n== $m" -ForegroundColor Cyan }

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Bad "This must run in an elevated PowerShell. Win+X, then A."
    exit 1
}

Head "OpenSSH server"
$cap = Get-WindowsCapability -Online -Name OpenSSH.Server* |
       Where-Object { $_.Name -like 'OpenSSH.Server*' } | Select-Object -First 1
if ($cap.State -ne 'Installed') {
    Write-Host "  installing (this takes a minute and prints no progress)..."
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
    Ok "installed"
} else { Ok "already installed" }

Set-Service -Name sshd -StartupType Automatic
if ((Get-Service sshd).Status -ne 'Running') { Start-Service sshd }
Ok ("service: {0}, start type automatic" -f (Get-Service sshd).Status)

Head "Authorized key"
# Administrators authenticate through a machine-wide file on Windows, not ~/.ssh.
$isAdminUser = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
                   [Security.Principal.WindowsBuiltInRole]::Administrator)
$akFile = if ($isAdminUser) { "$env:ProgramData\ssh\administrators_authorized_keys" }
          else { "$env:USERPROFILE\.ssh\authorized_keys" }
$akDir = Split-Path $akFile
if (-not (Test-Path $akDir)) { New-Item -ItemType Directory -Path $akDir -Force | Out-Null }

$existing = if (Test-Path $akFile) { Get-Content $akFile } else { @() }
if ($existing -contains $PublicKey) {
    Ok "key already present in $akFile"
} else {
    Add-Content -Path $akFile -Value $PublicKey
    Ok "key added to $akFile"
}

if ($isAdminUser) {
    # administrators_authorized_keys is ignored unless its ACL is exactly this
    icacls $akFile /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null
    Ok "ACL tightened (sshd ignores this file otherwise)"
}

Head "Password authentication"
$cfg = "$env:ProgramData\ssh\sshd_config"
if (Test-Path $cfg) {
    $c = Get-Content $cfg
    $c = $c -replace '^\s*#?\s*PasswordAuthentication.*', 'PasswordAuthentication no'
    if ($c -notmatch 'PasswordAuthentication no') { $c += "`nPasswordAuthentication no" }
    Set-Content -Path $cfg -Value $c
    Restart-Service sshd
    Ok "password auth disabled, service restarted"
} else { Warn "sshd_config not found; password auth NOT disabled" }

Head "Firewall"
# The reason this script exists. The tailnet adapter is normally classified Public, so a
# rule created without an explicit profile does not apply to it and the port stays shut
# while every command reports success.
Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
$ts = Get-NetAdapter | Where-Object { $_.InterfaceDescription -like '*Tailscale*' -or $_.Name -like '*Tailscale*' }
if ($TailnetOnly -and $ts) {
    New-NetFirewallRule -Name $RuleName -DisplayName "agent-host SSH (tailnet only)" `
        -Enabled True -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow `
        -Profile Any -InterfaceAlias $ts.Name | Out-Null
    Ok ("rule scoped to interface '{0}', all profiles" -f $ts.Name)
} else {
    if ($TailnetOnly) { Warn "no Tailscale adapter found; falling back to all interfaces" }
    New-NetFirewallRule -Name $RuleName -DisplayName "agent-host SSH" `
        -Enabled True -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow `
        -Profile Any | Out-Null
    Warn "rule applies to ALL interfaces. Narrow this when you can."
}

Head "Verify"
$listening = (netstat -an | Select-String ':22\s.*LISTENING')
if ($listening) { Ok "sshd is listening on 22" } else { Bad "nothing is listening on 22" }

$tsIp = $null
try { $tsIp = (& tailscale ip -4 2>$null | Select-Object -First 1).Trim() } catch { }
if ($tsIp) {
    $t = Test-NetConnection -ComputerName $tsIp -Port 22 -WarningAction SilentlyContinue
    if ($t.TcpTestSucceeded) { Ok "reachable on the tailnet at $tsIp" }
    else { Bad "NOT reachable at $tsIp. The firewall rule is not applying to that adapter." }
} else { Warn "tailscale ip returned nothing; cannot self-verify tailnet reachability" }

Write-Host "`nRevoke later with: agent-host revoke <name>, or by hand:" -ForegroundColor White
Write-Host "  Remove-NetFirewallRule -Name $RuleName; Stop-Service sshd; Set-Service sshd -StartupType Disabled"
