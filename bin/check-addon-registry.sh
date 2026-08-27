#!/usr/bin/env bash
# Every directory in addons/ must have a row in the ANATOMY add-on table.
#
# An add-on nobody can find is an add-on that gets re-invented. This guard exists
# because three of seventeen add-ons had no registry row at all, and the ones that
# get re-invented are the ones whose directory name does not say what they do.
#
#   bin/check-addon-registry.sh          # report and fail on any gap
#
# Exit 0 clean, 1 on a missing row.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANATOMY="$HERE/docs/ANATOMY.md"
[[ -f "$ANATOMY" ]] || { echo "check-addon-registry: $ANATOMY not found" >&2; exit 2; }

missing=()
for d in "$HERE"/addons/*/; do
  name="$(basename "$d")"
  # a registry row starts the line, names the add-on in backticks, and is a table cell
  if ! grep -qE "^\| \`${name}\` \|" "$ANATOMY"; then
    missing+=("$name")
  fi
done

if (( ${#missing[@]} )); then
  echo "check-addon-registry: ${#missing[@]} add-on(s) have no row in docs/ANATOMY.md:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo >&2
  echo "Add a row to the 'Optional add-ons' table. An add-on that is not in the" >&2
  echo "registry cannot be found by anyone who did not already know it existed." >&2
  exit 1
fi

echo "check-addon-registry: all $(ls -d "$HERE"/addons/*/ | wc -l | tr -d ' ') add-ons are in the registry"
