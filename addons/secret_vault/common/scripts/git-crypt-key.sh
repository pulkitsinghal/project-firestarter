#!/usr/bin/env bash
# git-crypt-key.sh — store / restore a repository's git-crypt symmetric key in
# the secret vault under the conventional name "git-crypt: <repo>". macOS + Linux.
#
# Generalises the ad-hoc ~/bin/git-crypt-key-store: same naming convention and
# 1Password + OS-store redundancy, now with an on-disk backup, fingerprint
# verification, and cross-platform restore — via the generic secret-store/get.
#
#   ./git-crypt-key.sh store [repo] [--key <path>]   # export this repo's key → vault
#   ./git-crypt-key.sh restore [repo] [--unlock]     # vault → key file (and optionally unlock)
#
# <repo> defaults to the basename of the current git worktree. The git-crypt key
# is exported to a 0600 temp file, stored, then securely deleted — it is never
# printed and never passed as an argument.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=secret-vault-lib.sh
. "$SCRIPT_DIR/secret-vault-lib.sh"

# git-crypt keys were historically stored under OS account "git-crypt"; keep that
# so existing Keychain / 1Password items keep resolving.
GC_ACCOUNT="git-crypt"

usage() {
  cat >&2 <<'EOF'
usage: git-crypt-key.sh <store|restore> [repo] [options]

  store [repo] [--key <path>]     Store the repo's git-crypt key in the vault.
                                  Default: `git crypt export-key` the current repo.
  restore [repo] [--out <path>] [--unlock]
                                  Fetch the key from the vault. --unlock runs
                                  `git crypt unlock <keyfile>` in the current repo.

  repo            Repository label (default: basename of the git worktree root).
  --op-vault <v>  1Password vault to use.
  -h, --help      Show this help.

The vault item is named "git-crypt: <repo>".
EOF
  exit "${1:-2}"
}

[ $# -ge 1 ] || usage
CMD="$1"; shift || true

REPO=""; KEY_PATH=""; OUT_PATH=""; DO_UNLOCK=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --key) KEY_PATH="${2:-}"; shift 2 ;;
    --out) OUT_PATH="${2:-}"; shift 2 ;;
    --unlock) DO_UNLOCK=1; shift ;;
    --op-vault) SV_OP_VAULT="${2:-}"; export SECRET_VAULT_OP_VAULT="$SV_OP_VAULT"; shift 2 ;;
    -*) sv_err "unknown option: $1"; usage ;;
    *) if [ -z "$REPO" ]; then REPO="$1"; shift; else sv_err "unexpected argument: $1"; usage; fi ;;
  esac
done

git_toplevel() { git rev-parse --show-toplevel 2>/dev/null; }
default_repo() {
  local top; top="$(git_toplevel)" || true
  [ -n "$top" ] && basename "$top"
}

[ -n "$REPO" ] || REPO="$(default_repo)"
[ -n "$REPO" ] || sv_die "no repo given and not inside a git worktree"
NAME="git-crypt: $REPO"

command -v git-crypt >/dev/null 2>&1 || sv_die "git-crypt is not installed"

case "$CMD" in
  store)
    TMP=""
    if [ -n "$KEY_PATH" ]; then
      [ -f "$KEY_PATH" ] || sv_die "no such key file: $KEY_PATH"
      SRC="$KEY_PATH"
    else
      TMP="$(sv_mktemp)"
      trap 'sv_shred "$TMP"' EXIT INT TERM
      git crypt export-key "$TMP" >/dev/null 2>&1 || sv_die "git crypt export-key failed (is this a git-crypt repo you've unlocked?)"
      SRC="$TMP"
    fi
    "$SCRIPT_DIR/secret-store.sh" "$NAME" --file "$SRC" --os-account "$GC_ACCOUNT"
    ;;
  restore)
    if [ "$DO_UNLOCK" -eq 1 ] && [ -z "$OUT_PATH" ]; then
      # Unlock directly from an ephemeral keyfile, then shred it — the key never
      # persists on disk beyond git-crypt's own .git/git-crypt/keys copy.
      TMP="$(sv_mktemp)"
      trap 'sv_shred "$TMP"' EXIT INT TERM
      "$SCRIPT_DIR/secret-get.sh" "$NAME" --file "$TMP" --os-account "$GC_ACCOUNT" >/dev/null
      git crypt unlock "$TMP" || sv_die "git crypt unlock failed"
      sv_err "✓ unlocked $(git_toplevel) with the key for '$REPO'"
    else
      [ -n "$OUT_PATH" ] || OUT_PATH="./git-crypt-$(sv_slug "$REPO").key"
      "$SCRIPT_DIR/secret-get.sh" "$NAME" --file "$OUT_PATH" --os-account "$GC_ACCOUNT" >/dev/null
      sv_err "✓ wrote the git-crypt key for '$REPO' to $OUT_PATH (0600)"
      [ "$DO_UNLOCK" -eq 1 ] && { git crypt unlock "$OUT_PATH" || sv_die "git crypt unlock failed"; }
    fi
    ;;
  -h|--help) usage 0 ;;
  *) sv_err "unknown command: $CMD"; usage ;;
esac
