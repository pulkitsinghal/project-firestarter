#!/usr/bin/env bash
# secret-vault-lib.sh — shared helpers for the secret_vault add-on (POSIX / macOS + Linux).
#
# SOURCED, not run. `secret-store.sh` and `secret-get.sh` dot-source this file.
# It contains the durable-store adapters (1Password `op`, OS secret store, on-disk
# backup) and the sha256 fingerprint helper.
#
# ── Guardrails baked into this library (see docs/SECRETS.md) ──────────────────
#   * The secret VALUE is never accepted as a command-line argument (argv is
#     world-readable via `ps`). Callers stream bytes through a locked temp file.
#   * Nothing here echoes, logs, or prints a secret value. Only the sha256
#     fingerprint (which is not secret) and per-store status are ever printed.
#   * The OS secret store holds a base64 encoding of the raw bytes so arbitrary
#     binary secrets (e.g. a git-crypt symmetric key) round-trip losslessly.
#   * The canonical fingerprint is sha256 of the RAW secret bytes; every store
#     must read back to the same fingerprint or the operation FAILS closed.

# Never let `set -x` from a caller leak a value into a log.
set +x 2>/dev/null || true

# ── Layout (override via env) ────────────────────────────────────────────────
SECRET_VAULT_HOME="${SECRET_VAULT_HOME:-$HOME/.secret-vault}"
SV_BACKUP_DIR="${SECRET_VAULT_BACKUP_DIR:-$SECRET_VAULT_HOME/backups}"
SV_INDEX_DIR="${SECRET_VAULT_INDEX_DIR:-$SECRET_VAULT_HOME/index}"
# Generic OS-store account; the git-crypt wrapper overrides it to "git-crypt"
# for backward-compat with the pre-existing `git-crypt: <repo>` convention.
SV_OS_ACCOUNT="${SECRET_VAULT_OS_ACCOUNT:-secret-vault}"
# Optional 1Password vault (leave empty to use the account default).
SV_OP_VAULT="${SECRET_VAULT_OP_VAULT:-}"
# Optional macOS keychain to target instead of the default login keychain
# (e.g. a dedicated automation keychain). Empty = default keychain.
SV_MACOS_KEYCHAIN="${SECRET_VAULT_MACOS_KEYCHAIN:-}"

sv_err()  { printf '%s\n' "$*" >&2; }
sv_die()  { sv_err "✗ $*"; exit 1; }

sv_os() {  # -> darwin | linux | unknown
  case "$(uname -s 2>/dev/null)" in
    Darwin) echo darwin ;;
    Linux)  echo linux ;;
    *)      echo unknown ;;
  esac
}

# sha256 of a file's bytes -> lowercase hex. Tries the common tools in turn so
# the library is dependency-free on a stock macOS or Linux box.
sv_sha256_file() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$f" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$f" | awk '{print $NF}'
  else
    sv_die "no sha256 tool found (need sha256sum, shasum, or openssl)"
  fi
}

# Portable base64 encode/decode (no line wraps) via openssl, which behaves the
# same on macOS (BSD) and Linux (GNU) — unlike `base64 -d` vs `-D`.
sv_b64_encode_file() { openssl base64 -A < "$1"; }             # file  -> b64 on stdout
sv_b64_decode_to()   { openssl base64 -d -A > "$2" < "$1"; }   # b64 file $1 -> raw file $2

# Best-effort secure delete of a temp file (the durable backup is deliberately kept).
sv_shred() {
  [ -n "${1:-}" ] && [ -f "$1" ] || return 0
  if   command -v shred  >/dev/null 2>&1; then shred -u "$1" 2>/dev/null && return 0
  elif command -v gshred >/dev/null 2>&1; then gshred -u "$1" 2>/dev/null && return 0
  fi
  # macOS/BSD `rm -P` overwrites before unlinking; fall back to plain rm.
  rm -P "$1" 2>/dev/null || rm -f "$1" 2>/dev/null || true
}

# Create a 0600 temp file with a restrictive umask.
sv_mktemp() { ( umask 077; mktemp "${TMPDIR:-/tmp}/secret-vault.XXXXXX" ); }

# ── 1Password (op) adapter — stores the secret as a document titled <name> ────
sv_op_available() { command -v op >/dev/null 2>&1; }

# Build the optional `--vault <v>` argv into the SV_OP_VF array (empty when unset).
sv_op_vf() { SV_OP_VF=(); [ -n "$SV_OP_VAULT" ] && SV_OP_VF=(--vault "$SV_OP_VAULT"); }

sv_op_put() {  # <name> <rawfile>  -> 0 on success
  local name="$1" file="$2"; sv_op_vf
  # ${arr[@]+"${arr[@]}"} expands to nothing on an empty array without tripping
  # `set -u` on bash 3.2 (macOS system bash).
  if op document get "$name" ${SV_OP_VF[@]+"${SV_OP_VF[@]}"} >/dev/null 2>&1; then
    op document edit "$name" "$file" ${SV_OP_VF[@]+"${SV_OP_VF[@]}"} >/dev/null 2>&1
  else
    op document create "$file" --title "$name" ${SV_OP_VF[@]+"${SV_OP_VF[@]}"} >/dev/null 2>&1
  fi
}

sv_op_get_to() {  # <name> <outfile>  -> 0 on success (raw bytes written to outfile)
  local name="$1" out="$2"; sv_op_vf
  op document get "$name" ${SV_OP_VF[@]+"${SV_OP_VF[@]}"} --out-file "$out" >/dev/null 2>&1 && [ -s "$out" ]
}

# ── OS secret store adapter (base64 payload) ─────────────────────────────────
#   macOS  -> login Keychain via `security`
#   Linux  -> Secret Service (GNOME Keyring / KWallet) via `secret-tool`
sv_os_store_available() {
  case "$(sv_os)" in
    darwin) command -v security   >/dev/null 2>&1 ;;
    linux)  command -v secret-tool >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

sv_os_put() {  # <name> <rawfile>  -> 0 on success
  local name="$1" file="$2" b64
  b64="$(sv_b64_encode_file "$file")" || return 1
  case "$(sv_os)" in
    darwin)
      # -U updates in place if the item already exists. The b64 value is briefly
      # visible in this one `security` process's argv (a known macOS limitation);
      # it is never written to a log and the process is local + short-lived.
      security add-generic-password -U -a "$SV_OS_ACCOUNT" -s "$name" \
        -T /usr/bin/security -w "$b64" ${SV_MACOS_KEYCHAIN:+"$SV_MACOS_KEYCHAIN"} >/dev/null 2>&1
      ;;
    linux)
      # secret-tool reads the secret from stdin — never from argv.
      printf '%s' "$b64" | secret-tool store --label="$name" \
        service "$name" account "$SV_OS_ACCOUNT" >/dev/null 2>&1
      ;;
    *) return 1 ;;
  esac
}

sv_os_get_to() {  # <name> <outfile>  -> 0 on success (raw bytes written to outfile)
  local name="$1" out="$2" b64f rc=0
  b64f="$(sv_mktemp)" || return 1
  case "$(sv_os)" in
    darwin)
      security find-generic-password -a "$SV_OS_ACCOUNT" -s "$name" -w \
        ${SV_MACOS_KEYCHAIN:+"$SV_MACOS_KEYCHAIN"} 2>/dev/null \
        | tr -d '\r\n' > "$b64f" || rc=1 ;;
    linux)
      secret-tool lookup service "$name" account "$SV_OS_ACCOUNT" 2>/dev/null \
        | tr -d '\r\n' > "$b64f" || rc=1 ;;
    *) rc=1 ;;
  esac
  if [ "$rc" -eq 0 ] && [ -s "$b64f" ]; then
    sv_b64_decode_to "$b64f" "$out" 2>/dev/null || rc=1
  else
    rc=1
  fi
  sv_shred "$b64f"
  [ "$rc" -eq 0 ] && [ -s "$out" ]
}

sv_os_store_label() {  # human label for status output
  case "$(sv_os)" in
    darwin) echo "Keychain (macOS)" ;;
    linux)  echo "Secret Service (Linux)" ;;
    *)      echo "OS secret store" ;;
  esac
}

# ── On-disk backup adapter (raw bytes, 0600) ─────────────────────────────────
sv_backup_path() { printf '%s/%s.secret' "$SV_BACKUP_DIR" "$(sv_slug "$1")"; }
sv_index_path()  { printf '%s/%s.sha256' "$SV_INDEX_DIR"  "$(sv_slug "$1")"; }

# Filesystem-safe slug for a secret name (e.g. "git-crypt: repo" -> "git-crypt_repo").
sv_slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

sv_backup_put() {  # <name> <rawfile>
  local name="$1" file="$2" dest; dest="$(sv_backup_path "$name")"
  ( umask 077; mkdir -p "$SV_BACKUP_DIR" ) && chmod 700 "$SV_BACKUP_DIR" 2>/dev/null || true
  ( umask 077; cp "$file" "$dest" ) && chmod 600 "$dest"
}

sv_backup_get_to() {  # <name> <outfile>
  local name="$1" out="$2" src; src="$(sv_backup_path "$name")"
  [ -f "$src" ] || return 1
  cp "$src" "$out" && [ -s "$out" ]
}

# ── Fingerprint index (non-secret: it stores only the sha256) ─────────────────
sv_index_put() {  # <name> <fingerprint>
  local name="$1" fp="$2" dest; dest="$(sv_index_path "$name")"
  ( umask 077; mkdir -p "$SV_INDEX_DIR" )
  printf '%s\n' "$fp" > "$dest"
}

sv_index_get() {  # <name> -> prints stored fingerprint, or nothing
  local src; src="$(sv_index_path "$1")"
  [ -f "$src" ] && awk 'NR==1{print $1}' "$src"
}
