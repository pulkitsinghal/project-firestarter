#!/usr/bin/env bash
# macOS read-only ledger validation. JXA is built into macOS.
set -u
EXPECTED_REPO='{{ trusted_workstation_repo }}'
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"

if [ -z "${BASH_VERSION:-}" ]; then printf 'BLOCKED this command requires Bash\n' >&2; exit 2; fi
case "${BASH_VERSINFO[0]:-0}" in ''|*[!0-9]*) printf 'BLOCKED unusable Bash version\n' >&2; exit 2;; esac
if [ "${BASH_VERSINFO[0]}" -lt 3 ]; then printf 'BLOCKED Bash 3.2 or newer is required\n' >&2; exit 2; fi
if [ "$(uname -s 2>/dev/null || true)" != 'Darwin' ]; then printf 'BLOCKED shell status is supported on macOS only\n' >&2; exit 2; fi
if [ ! -x /usr/bin/osascript ]; then printf 'BLOCKED macOS JavaScript runtime is unavailable\n' >&2; exit 2; fi

if [ "${1:-}" = '--ledger' ] && [ -n "${2:-}" ]; then ledger=$2
elif [ -n "${TRUSTED_WORKSTATION_LEDGER:-}" ]; then ledger=$TRUSTED_WORKSTATION_LEDGER
else ledger="$HOME/Library/Application Support/{{ project_name }}/trusted-workstation-ledger.json"; fi

if [ "${#ledger}" -gt 2048 ] || printf '%s' "$ledger" | LC_ALL=C grep -q '[[:cntrl:]]'; then
  printf 'BLOCKED ledger path is malformed\n' >&2; exit 1
fi
if [ ! -f "$ledger" ]; then printf 'NOT_ENROLLED ledger is missing\n'; exit 1; fi
cursor=$ledger
while [ -n "$cursor" ] && [ "$cursor" != "/" ]; do
  if [ -L "$cursor" ]; then printf 'BLOCKED ledger path contains a link\n' >&2; exit 1; fi
  cursor=${cursor%/*}; [ -n "$cursor" ] || cursor=/
done
/usr/bin/osascript -l JavaScript "$SCRIPT_DIR/trusted-workstation-ledger-validator.js" "$ledger" "$EXPECTED_REPO"
