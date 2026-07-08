#!/usr/bin/env bash
# Preflight .env validation — fail fast, BEFORE boot/deploy, when a required
# variable is unset or still a placeholder. SECURITY.md says "read secrets from
# env, fail closed"; this verifies the env is actually populated so a half-filled
# .env surfaces one clear message instead of a confusing error deep in the stack.
#
# `.env.example` is the manifest. A variable is REQUIRED if its example value is
# the sentinel __REPLACE_ME__ (or the line is tagged `# required`); anything with
# a real default value is OPTIONAL. Workflow:  cp .env.example .env  → fill it in
# → `make verify-env`.
#
# No host SDK (bash + coreutils only). It deliberately does NOT
# `export $(cat .env | xargs)` — that breaks on spaces/quotes and leaks values —
# it parses line by line and never sources the file.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

example=".env.example"
envfile="${ENV_FILE:-.env}"

[ -f "$example" ] || { echo "· no $example — nothing to verify."; exit 0; }

# Build the list of required keys from the manifest.
required=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ''|\#*) continue ;;                       # skip blank lines and comments
  esac
  key="${line%%=*}"
  val="${line#*=}"
  key="$(printf '%s' "$key" | tr -d '[:space:]')"
  [ -n "$key" ] || continue
  case "$line" in
    *"# required"*) required="$required $key" ; continue ;;
    *"# optional"*) continue ;;
    *) case "$val" in *__REPLACE_ME__*) required="$required $key" ;; esac ;;
  esac
done < "$example"

# Read one key's value from $envfile (last assignment wins) without sourcing it.
getval() {
  grep -E "^[[:space:]]*$1=" "$envfile" 2>/dev/null | tail -n1 | sed -E "s/^[[:space:]]*$1=//"
}

if [ -z "$(printf '%s' "$required" | tr -d '[:space:]')" ]; then
  echo "✓ verify-env: no required vars declared in $example (nothing to check)."
  exit 0
fi

if [ ! -f "$envfile" ]; then
  echo "✗ $envfile not found, but $example declares required vars:"
  for k in $required; do echo "    - $k"; done
  echo "  → cp $example $envfile   and fill in the values."
  exit 1
fi

missing=0
for k in $required; do
  v="$(getval "$k")"
  # Strip surrounding whitespace and one layer of matching quotes for the test.
  vt="$(printf '%s' "$v" | sed -E "s/^[[:space:]]*//; s/[[:space:]]*$//; s/^\"(.*)\"$/\1/; s/^'(.*)'$/\1/")"
  if [ -z "$vt" ]; then
    echo "✗ $k — required but not set in $envfile"
    missing=$((missing + 1))
  elif printf '%s' "$vt" | grep -q '__REPLACE_ME__'; then
    echo "✗ $k — still the placeholder __REPLACE_ME__"
    missing=$((missing + 1))
  else
    echo "✓ $k"
  fi
done

if [ "$missing" -gt 0 ]; then
  echo "✗ verify-env: $missing required var(s) unset or placeholder in $envfile."
  exit 1
fi
echo "✓ verify-env: all required vars set."
exit 0
