#!/usr/bin/env bash
# Propagate the canonical version (repo-root VERSION) into the files that carry a
# version literal: app/pubspec.yaml, services/pubspec.yaml, splash/package.json.
# Bump VERSION, then run this (or `make version-sync`). Host coreutils only — no
# language SDK required (honors the no-host-toolchains rule; sed/tr aren't SDKs).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V="$(tr -d '[:space:]' < "$ROOT/VERSION")"

if ! printf '%s' "$V" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.]+)?$'; then
  echo "VERSION '$V' is not valid semver" >&2
  exit 1
fi

# Portable in-place sed (GNU vs BSD).
sedi() { if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi; }

# Dart/Flutter pubspec `version: X.Y.Z(+build)` — replace only the semver core so
# any trailing +build number is preserved.
sedi -E "s/^(version: )[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.]+)?/\1$V/" "$ROOT/app/pubspec.yaml"
sedi -E "s/^(version: )[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.]+)?/\1$V/" "$ROOT/services/pubspec.yaml"
sedi -E "s/^([[:space:]]*\"version\": \")[^\"]*\"/\1$V\"/" "$ROOT/splash/package.json"

echo "synced version → $V"
echo "  app/pubspec.yaml, services/pubspec.yaml, splash/package.json"
echo "Next: update CHANGELOG.md, commit, and tag (git tag -a v$V)."
