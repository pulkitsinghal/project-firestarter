#!/usr/bin/env bash
# secret-store.sh — store a NAMED secret redundantly across durable stores and
# verify every copy by sha256 fingerprint (defense-in-redundancy). macOS + Linux.
#
# The secret VALUE is never passed as a command-line argument. Provide it via
# stdin (default), a file, or ask the tool to generate one:
#
#   op read 'op://Private/some-api/credential' | ./secret-store.sh MY_API_KEY
#   ./secret-store.sh MY_API_KEY --file ./key.bin
#   ./secret-store.sh MY_API_KEY --generate 32          # 32 random bytes
#
# It writes to (all that are available; at least two durable copies required):
#   1. 1Password        — `op document` titled <name>            (needs `op`, signed in)
#   2. OS secret store  — macOS Keychain / Linux Secret Service  (base64 payload)
#   3. On-disk backup   — ~/.secret-vault/backups/<slug>.secret  (raw bytes, 0600)
# then reads each copy back, hashes it, and ASSERTS every fingerprint matches.
# It prints ONLY the fingerprint + per-store status — never the secret value.
#
# Exit non-zero if fewer than two durable copies land, or if any copy's
# fingerprint disagrees with the source (fail closed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=secret-vault-lib.sh
. "$SCRIPT_DIR/secret-vault-lib.sh"

usage() {
  cat >&2 <<'EOF'
usage: secret-store.sh <name> [input] [options]

  <name>                  Logical secret name (e.g. MY_API_KEY, "git-crypt: repo").

input (choose one; default is stdin):
  (stdin)                 Read the raw secret bytes from stdin.
  --file <path>           Read the raw secret bytes from a file.
  --generate [BYTES]      Generate BYTES (default 32) of random bytes as the secret.

options:
  --os-account <acct>     OS-store account label (default: secret-vault).
  --op-vault <vault>      1Password vault to store the document in.
  --no-op                 Skip the 1Password copy.
  --no-os                 Skip the OS-secret-store copy.
  -h, --help              Show this help.

Never pass the secret value as an argument; argv is world-readable via `ps`.
EOF
  exit "${1:-2}"
}

NAME=""; INPUT_MODE="stdin"; INPUT_FILE=""; GEN_BYTES=32
USE_OP=1; USE_OS=1

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --file) INPUT_MODE="file"; INPUT_FILE="${2:-}"; shift 2 ;;
    --generate) INPUT_MODE="generate"; case "${2:-}" in ''|*[!0-9]*) shift 1 ;; *) GEN_BYTES="$2"; shift 2 ;; esac ;;
    --os-account) SV_OS_ACCOUNT="${2:-}"; shift 2 ;;
    --op-vault) SV_OP_VAULT="${2:-}"; shift 2 ;;
    --no-op) USE_OP=0; shift ;;
    --no-os) USE_OS=0; shift ;;
    --) shift; break ;;
    -*) sv_err "unknown option: $1"; usage ;;
    *) if [ -z "$NAME" ]; then NAME="$1"; shift; else sv_err "unexpected argument: $1"; usage; fi ;;
  esac
done

[ -n "$NAME" ] || usage

# ── Acquire the raw bytes into a locked temp file ─────────────────────────────
RAW="$(sv_mktemp)"
cleanup() { sv_shred "$RAW"; }
trap cleanup EXIT INT TERM

case "$INPUT_MODE" in
  file)
    [ -n "$INPUT_FILE" ] && [ -f "$INPUT_FILE" ] || sv_die "no such file: ${INPUT_FILE:-<missing>}"
    cat "$INPUT_FILE" > "$RAW" ;;
  generate)
    head -c "$GEN_BYTES" /dev/urandom > "$RAW" || sv_die "failed to read /dev/urandom" ;;
  stdin)
    if [ -t 0 ]; then sv_die "no secret on stdin (pipe it in, or use --file / --generate)"; fi
    cat > "$RAW" ;;
esac
[ -s "$RAW" ] || sv_die "the secret is empty; nothing to store"

FP="$(sv_sha256_file "$RAW")"

# ── Write + verify each store ─────────────────────────────────────────────────
DURABLE=0            # count of durable copies that stored AND verified
declare -a LINES=()

verify_store() {  # <label> <getter-fn>  -> checks a store read-back matches FP
  local label="$1" getter="$2" tmp back
  tmp="$(sv_mktemp)"
  if "$getter" "$NAME" "$tmp"; then
    back="$(sv_sha256_file "$tmp")"
    sv_shred "$tmp"
    if [ "$back" = "$FP" ]; then return 0; fi
    sv_shred "$tmp"; return 3   # mismatch
  fi
  sv_shred "$tmp"; return 1     # unreadable
}

# 1Password
if [ "$USE_OP" -eq 1 ] && sv_op_available; then
  if sv_op_put "$NAME" "$RAW" && verify_store "1Password" sv_op_get_to; then
    LINES+=("  1Password              : ok"); DURABLE=$((DURABLE+1))
  else
    LINES+=("  1Password              : FAILED (stored or verified badly)")
  fi
elif [ "$USE_OP" -eq 1 ]; then
  LINES+=("  1Password              : skipped (op not installed / not signed in)")
else
  LINES+=("  1Password              : skipped (--no-op)")
fi

# OS secret store
OS_LABEL="$(sv_os_store_label)"
if [ "$USE_OS" -eq 1 ] && sv_os_store_available; then
  if sv_os_put "$NAME" "$RAW" && verify_store "$OS_LABEL" sv_os_get_to; then
    LINES+=("  $OS_LABEL : ok"); DURABLE=$((DURABLE+1))
  else
    LINES+=("  $OS_LABEL : FAILED (stored or verified badly)")
  fi
elif [ "$USE_OS" -eq 1 ]; then
  LINES+=("  $OS_LABEL : skipped (no OS secret store on this host)")
else
  LINES+=("  $OS_LABEL : skipped (--no-os)")
fi

# On-disk backup (always attempted; it is the recovery floor)
if sv_backup_put "$NAME" "$RAW" && verify_store "backup" sv_backup_get_to; then
  LINES+=("  backup ($(sv_backup_path "$NAME")): ok"); DURABLE=$((DURABLE+1))
else
  LINES+=("  backup ($(sv_backup_path "$NAME")): FAILED")
fi

# Record the fingerprint index (non-secret) for fast single-store verification on get.
sv_index_put "$NAME" "$FP"

# ── Report ────────────────────────────────────────────────────────────────────
printf '\nsecret: %s\n' "$NAME"
printf 'fingerprint (sha256): %s\n' "$FP"
for l in "${LINES[@]}"; do printf '%s\n' "$l"; done

if [ "$DURABLE" -lt 2 ]; then
  sv_die "only $DURABLE durable copy stored — need at least 2 (redundancy floor). Secret is NOT safely stored."
fi
printf '\n✓ %d durable copies, all fingerprints match (%s…)\n' "$DURABLE" "${FP:0:12}"
