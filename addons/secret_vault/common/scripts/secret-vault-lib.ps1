# secret-vault-lib.ps1 — shared helpers for the secret_vault add-on (Windows).
#
# DOT-SOURCED, not run: `. "$PSScriptRoot\secret-vault-lib.ps1"`. Provides the
# durable-store adapters for Windows and the sha256 fingerprint helper.
#
# Durable stores on Windows:
#   1. 1Password           — `op document` titled <name>            (cross-platform CLI)
#   2. Windows Credential  — Credential Manager (generic) via advapi32 P/Invoke
#      Manager               (a REAL OS secret store; no external module needed)
#   3. On-disk backup      — %USERPROFILE%\.secret-vault\backups\<slug>.secret,
#                            DPAPI-encrypted at rest (CurrentUser) + ACL-locked.
#
# Guardrails (see docs/SECRETS.md): the secret value is never placed in a
# command-line argument, never echoed/logged, and only the sha256 fingerprint
# (not secret) and per-store status are printed. Fingerprint = sha256 of the RAW
# bytes; every store must read back to the same fingerprint or the op FAILS.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Layout (override via env) ────────────────────────────────────────────────
$script:SvHome      = if ($env:SECRET_VAULT_HOME)        { $env:SECRET_VAULT_HOME }        else { Join-Path $HOME '.secret-vault' }
$script:SvBackupDir = if ($env:SECRET_VAULT_BACKUP_DIR)  { $env:SECRET_VAULT_BACKUP_DIR }  else { Join-Path $script:SvHome 'backups' }
$script:SvIndexDir  = if ($env:SECRET_VAULT_INDEX_DIR)   { $env:SECRET_VAULT_INDEX_DIR }   else { Join-Path $script:SvHome 'index' }
# On Windows the Credential Manager target embeds the account so multiple logical
# owners don't collide; git-crypt keys keep the historical "git-crypt" account.
$script:SvOsAccount = if ($env:SECRET_VAULT_OS_ACCOUNT)  { $env:SECRET_VAULT_OS_ACCOUNT }  else { 'secret-vault' }
$script:SvOpVault   = if ($env:SECRET_VAULT_OP_VAULT)    { $env:SECRET_VAULT_OP_VAULT }    else { '' }

function Sv-Die([string]$msg) { Write-Error "x $msg"; exit 1 }
function Sv-Info([string]$msg) { [Console]::Error.WriteLine($msg) }

function Sv-Slug([string]$name) {
  return ($name -replace '[^A-Za-z0-9._-]', '_')
}

function Sv-BackupPath([string]$name) { Join-Path $script:SvBackupDir ((Sv-Slug $name) + '.secret') }
function Sv-IndexPath([string]$name)  { Join-Path $script:SvIndexDir  ((Sv-Slug $name) + '.sha256') }

# ── sha256 ───────────────────────────────────────────────────────────────────
function Sv-Sha256Hex([byte[]]$bytes) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try { return (($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join '') }
  finally { $sha.Dispose() }
}
function Sv-Sha256File([string]$path) { return Sv-Sha256Hex ([System.IO.File]::ReadAllBytes($path)) }

# ── Windows Credential Manager (generic creds) via advapi32 ──────────────────
if (-not ([System.Management.Automation.PSTypeName]'SvCredMan').Type) {
  Add-Type -Namespace '' -Name 'SvCredMan' -MemberDefinition @'
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct CREDENTIAL {
    public uint Flags;
    public uint Type;
    [MarshalAs(UnmanagedType.LPWStr)] public string TargetName;
    [MarshalAs(UnmanagedType.LPWStr)] public string Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
    public uint CredentialBlobSize;
    public IntPtr CredentialBlob;
    public uint Persist;
    public uint AttributeCount;
    public IntPtr Attributes;
    [MarshalAs(UnmanagedType.LPWStr)] public string TargetAlias;
    [MarshalAs(UnmanagedType.LPWStr)] public string UserName;
  }
  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  public static extern bool CredWriteW([In] ref CREDENTIAL userCredential, uint flags);
  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  public static extern bool CredReadW(string target, uint type, uint flags, out IntPtr credential);
  [DllImport("advapi32.dll", SetLastError = true)]
  public static extern void CredFree([In] IntPtr buffer);
  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  public static extern bool CredDeleteW(string target, uint type, uint flags);
'@
}

$script:SV_CRED_GENERIC = 1        # CRED_TYPE_GENERIC
$script:SV_CRED_PERSIST = 2        # CRED_PERSIST_LOCAL_MACHINE

function Sv-CredTarget([string]$name) { return "$($script:SvOsAccount):$name" }

function Sv-CredSet([string]$name, [byte[]]$blob) {
  if ($blob.Length -gt 2560) { throw "secret exceeds the Credential Manager 2560-byte blob limit ($($blob.Length) bytes)" }
  $cred = New-Object SvCredMan+CREDENTIAL
  $cred.Type = $script:SV_CRED_GENERIC
  $cred.TargetName = Sv-CredTarget $name
  $cred.UserName = $script:SvOsAccount
  $cred.Persist = $script:SV_CRED_PERSIST
  $cred.CredentialBlobSize = [uint32]$blob.Length
  $ptr = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($blob.Length)
  try {
    [System.Runtime.InteropServices.Marshal]::Copy($blob, 0, $ptr, $blob.Length)
    $cred.CredentialBlob = $ptr
    if (-not [SvCredMan]::CredWriteW([ref]$cred, 0)) {
      throw "CredWrite failed (Win32 error $([System.Runtime.InteropServices.Marshal]::GetLastWin32Error()))"
    }
  } finally {
    [System.Runtime.InteropServices.Marshal]::FreeHGlobal($ptr)
  }
}

function Sv-CredGet([string]$name) {   # -> byte[] or $null
  $target = Sv-CredTarget $name
  $credPtr = [IntPtr]::Zero
  if (-not [SvCredMan]::CredReadW($target, $script:SV_CRED_GENERIC, 0, [ref]$credPtr)) { return $null }
  try {
    $cred = [System.Runtime.InteropServices.Marshal]::PtrToStructure($credPtr, [Type]([SvCredMan+CREDENTIAL]))
    $size = [int]$cred.CredentialBlobSize
    $bytes = New-Object byte[] $size
    if ($size -gt 0) { [System.Runtime.InteropServices.Marshal]::Copy($cred.CredentialBlob, $bytes, 0, $size) }
    return ,$bytes
  } finally {
    [SvCredMan]::CredFree($credPtr)
  }
}

function Sv-OsStoreAvailable { return $true }   # Credential Manager is always present on Windows
function Sv-OsStoreLabel { return 'Credential Manager (Windows)' }

# ── DPAPI (on-disk backup at rest) ───────────────────────────────────────────
# System.Security holds ProtectedData on Windows PowerShell 5.1; the type also
# auto-resolves on modern Windows PowerShell. Swallow the load error on non-
# Windows hosts (where DPAPI is unsupported anyway) so dot-sourcing never aborts.
try { Add-Type -AssemblyName System.Security -ErrorAction Stop } catch { }
function Sv-Protect([byte[]]$raw) {
  return [System.Security.Cryptography.ProtectedData]::Protect($raw, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
}
function Sv-Unprotect([byte[]]$enc) {
  return [System.Security.Cryptography.ProtectedData]::Unprotect($enc, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
}

function Sv-LockAcl([string]$path) {
  # Break inheritance and grant only the current user. Best-effort.
  try {
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $path /inheritance:r /grant:r "${me}:F" | Out-Null
  } catch { }
}

function Sv-BackupSet([string]$name, [byte[]]$raw) {
  if (-not (Test-Path $script:SvBackupDir)) { New-Item -ItemType Directory -Force -Path $script:SvBackupDir | Out-Null }
  $dest = Sv-BackupPath $name
  [System.IO.File]::WriteAllBytes($dest, (Sv-Protect $raw))
  Sv-LockAcl $dest
}
function Sv-BackupGet([string]$name) {   # -> byte[] or $null
  $src = Sv-BackupPath $name
  if (-not (Test-Path $src)) { return $null }
  return ,(Sv-Unprotect ([System.IO.File]::ReadAllBytes($src)))
}

# ── 1Password (op) adapter ───────────────────────────────────────────────────
function Sv-OpAvailable { return [bool](Get-Command op -ErrorAction SilentlyContinue) }
function Sv-OpVaultArgs { if ($script:SvOpVault) { return @('--vault', $script:SvOpVault) } else { return @() } }

function Sv-OpSet([string]$name, [string]$file) {   # from a raw-bytes file
  $vf = @(Sv-OpVaultArgs)   # @() keeps an empty result an array (StrictMode-safe splat)
  & op document get $name @vf 2>$null 1>$null
  if ($LASTEXITCODE -eq 0) {
    & op document edit $name $file @vf 2>$null 1>$null
  } else {
    & op document create $file --title $name @vf 2>$null 1>$null
  }
  return ($LASTEXITCODE -eq 0)
}
function Sv-OpGet([string]$name, [string]$outFile) {   # writes raw bytes to $outFile
  $vf = @(Sv-OpVaultArgs)
  & op document get $name @vf --out-file $outFile 2>$null 1>$null
  return ($LASTEXITCODE -eq 0 -and (Test-Path $outFile) -and ((Get-Item $outFile).Length -gt 0))
}

# ── Fingerprint index (non-secret) ───────────────────────────────────────────
function Sv-IndexSet([string]$name, [string]$fp) {
  if (-not (Test-Path $script:SvIndexDir)) { New-Item -ItemType Directory -Force -Path $script:SvIndexDir | Out-Null }
  Set-Content -Path (Sv-IndexPath $name) -Value $fp -NoNewline -Encoding ascii
}
function Sv-IndexGet([string]$name) {
  $p = Sv-IndexPath $name
  if (Test-Path $p) { return (Get-Content -Raw -Path $p).Trim() } else { return '' }
}

# ── Locked temp file ─────────────────────────────────────────────────────────
function Sv-NewTemp {
  $p = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), 'secret-vault-' + [System.Guid]::NewGuid().ToString('N') + '.tmp')
  New-Item -ItemType File -Path $p -Force | Out-Null
  Sv-LockAcl $p
  return $p
}
function Sv-Shred([string]$path) {
  if (-not $path -or -not (Test-Path $path)) { return }
  try {
    $len = (Get-Item $path).Length
    if ($len -gt 0) {
      $rng = [byte[]]::new($len)
      [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($rng)
      [System.IO.File]::WriteAllBytes($path, $rng)
    }
  } catch { }
  Remove-Item -Force -Path $path -ErrorAction SilentlyContinue
}
