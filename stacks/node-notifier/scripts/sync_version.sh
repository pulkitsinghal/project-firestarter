#!/usr/bin/env bash
# Keep the canonical /VERSION, package.json, and package-lock.json aligned.
# Uses only host coreutils; Node remains container-only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V="$(tr -d '[:space:]' < "$ROOT/VERSION")"

if ! printf '%s' "$V" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.]+)?$'; then
  echo "VERSION '$V' is not valid semver" >&2
  exit 1
fi

sedi() {
  if sed --version >/dev/null 2>&1; then
    sed -i "$@"
  else
    sed -i '' "$@"
  fi
}

sedi -E "0,/^([[:space:]]*\"version\": \")[^\"]*\"/s//\\1$V\"/" "$ROOT/package.json"
awk -v version="$V" '
  BEGIN { changed = 0 }
  /^[[:space:]]*"version": "[^"]*",?$/ && changed < 2 {
    sub(/"version": "[^"]*"/, "\"version\": \"" version "\"")
    changed += 1
  }
  { print }
' "$ROOT/package-lock.json" > "$ROOT/package-lock.json.tmp"
mv "$ROOT/package-lock.json.tmp" "$ROOT/package-lock.json"

echo "synced version → $V"
echo "  package.json, package-lock.json"
