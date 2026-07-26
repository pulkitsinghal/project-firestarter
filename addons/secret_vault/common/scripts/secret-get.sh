#!/usr/bin/env bash
# secret-get.sh — retrieve a named secret for RUNTIME use, with primary-store
# fallback and fingerprint verification. macOS + Linux.
#
# Prefer streaming the secret straight into the consuming command so it never
# lands in a file or the shell's environment beyond the child that needs it:
#
#   ./secret-get.sh MY_API_KEY --exec API_KEY -- myserver --port 8080
#       ↑ fetches the secret, verifies it, exports API_KEY *only* into the
#         child's environment, then exec's the command. The value never appears
#         in argv, in a file, or in the parent shell.
#
# Other sinks:
#   ./secret-get.sh MY_API_KEY                 # stream to stdout (for a pipe)
#   ./secret-get.sh MY_API_KEY --file out.bin  # write to a 0600 file (binary-safe)
#
# Source order for --source auto (default): 1Password → OS store → backup;
# the first store that returns the secret wins. The retrieved value is hashed
# and checked against the recorded fingerprint (or a second store) before use.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=secret-vault-lib.sh
. "$SCRIPT_DIR/secret-vault-lib.sh"

usage() {
  cat >&2 <<'EOF'
usage: secret-get.sh <name> [sink] [options]

  <name>                  Logical secret name used at store time.

sink (choose one; default: stream to stdout):
  --exec <ENVVAR> -- cmd [args...]   Export the secret as $ENVVAR into the child
                                     environment only, then exec cmd. Never argv.
  --file <path>                      Write raw bytes to a 0600 file (binary-safe).
  --stdout                           Stream raw bytes to stdout (explicit default).

options:
  --source <auto|op|os|backup>  Which store to read (default: auto, with fallback).
  --os-account <acct>           OS-store account label (default: secret-vault).
  --op-vault <vault>            1Password vault to read the document from.
  --no-verify                   Skip the fingerprint check (not recommended).
  -h, --help                    Show this help.
EOF
  exit "${1:-2}"
}

NAME=""; SINK="stdout"; OUT_FILE=""; EXEC_ENV=""; SOURCE="auto"; VERIFY=1
declare -a EXEC_CMD=()

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --stdout) SINK="stdout"; shift ;;
    --file) SINK="file"; OUT_FILE="${2:-}"; shift 2 ;;
    --exec)
      SINK="exec"; EXEC_ENV="${2:-}"; shift 2
      [ "${1:-}" = "--" ] || { sv_err "--exec <ENVVAR> must be followed by -- <cmd>"; usage; }
      shift; EXEC_CMD=("$@"); break ;;
    --source) SOURCE="${2:-}"; shift 2 ;;
    --os-account) SV_OS_ACCOUNT="${2:-}"; shift 2 ;;
    --op-vault) SV_OP_VAULT="${2:-}"; shift 2 ;;
    --no-verify) VERIFY=0; shift ;;
    --) shift; break ;;
    -*) sv_err "unknown option: $1"; usage ;;
    *) if [ -z "$NAME" ]; then NAME="$1"; shift; else sv_err "unexpected argument: $1"; usage; fi ;;
  esac
done

[ -n "$NAME" ] || usage
[ "$SINK" = "exec" ] && { [ -n "$EXEC_ENV" ] || usage; [ "${#EXEC_CMD[@]}" -gt 0 ] || { sv_err "--exec needs a command after --"; usage; }; }
[ "$SINK" = "file" ] && { [ -n "$OUT_FILE" ] || usage; }

OUT="$(sv_mktemp)"
cleanup() { sv_shred "$OUT"; }
trap cleanup EXIT INT TERM

# ── Fetch (with fallback) ─────────────────────────────────────────────────────
FROM=""
try_source() {  # <label> <getter-fn>
  local label="$1" getter="$2"
  "$getter" "$NAME" "$OUT" && { FROM="$label"; return 0; }
  return 1
}

case "$SOURCE" in
  op)      sv_op_available       && try_source "1Password"          sv_op_get_to     || sv_die "not found in 1Password" ;;
  os)      sv_os_store_available && try_source "$(sv_os_store_label)" sv_os_get_to   || sv_die "not found in the OS secret store" ;;
  backup)  try_source "backup" sv_backup_get_to || sv_die "not found in the on-disk backup" ;;
  auto)
    { sv_op_available       && try_source "1Password"           sv_op_get_to;    } ||
    { sv_os_store_available && try_source "$(sv_os_store_label)" sv_os_get_to;   } ||
    try_source "backup" sv_backup_get_to ||
    sv_die "secret '$NAME' not found in any store" ;;
  *) sv_die "unknown --source '$SOURCE' (use auto|op|os|backup)" ;;
esac

# ── Verify fingerprint ────────────────────────────────────────────────────────
if [ "$VERIFY" -eq 1 ]; then
  GOT="$(sv_sha256_file "$OUT")"
  WANT="$(sv_index_get "$NAME" || true)"
  if [ -n "$WANT" ]; then
    [ "$GOT" = "$WANT" ] || sv_die "fingerprint mismatch (store '$FROM' returned $GOT, expected $WANT) — refusing to use it"
  else
    # No recorded fingerprint: cross-check against a *different* store when possible.
    ALT="$(sv_mktemp)"; other=""
    if [ "$FROM" != "backup" ] && sv_backup_get_to "$NAME" "$ALT"; then other="backup"
    elif [ "$FROM" != "1Password" ] && sv_op_available && sv_op_get_to "$NAME" "$ALT"; then other="1Password"
    elif sv_os_store_available && sv_os_get_to "$NAME" "$ALT"; then other="$(sv_os_store_label)"
    fi
    if [ -n "$other" ]; then
      [ "$(sv_sha256_file "$ALT")" = "$GOT" ] || { sv_shred "$ALT"; sv_die "cross-store fingerprint mismatch between '$FROM' and '$other'"; }
      sv_shred "$ALT"
    else
      sv_shred "$ALT"
      sv_err "⚠ no recorded fingerprint and no second store to cross-check '$NAME' (proceeding unverified)"
    fi
  fi
fi

sv_err "→ retrieved '$NAME' from $FROM"

# ── Deliver ───────────────────────────────────────────────────────────────────
case "$SINK" in
  stdout)
    cat "$OUT" ;;
  file)
    ( umask 077; cp "$OUT" "$OUT_FILE" ) && chmod 600 "$OUT_FILE"
    sv_err "→ wrote $OUT_FILE (0600)" ;;
  exec)
    # Read the whole file (incl. any trailing newline) into a variable via a
    # read delimited by NUL, then export it into THIS shell's environment (a
    # builtin — nothing shows up in `ps`) and exec. The child inherits $ENVVAR
    # in its environment; its argv contains only the command + its own args.
    val=""
    IFS= read -r -d '' val < "$OUT" || true
    sv_shred "$OUT"; trap - EXIT INT TERM
    export "${EXEC_ENV}=${val}"
    exec "${EXEC_CMD[@]}" ;;
esac
