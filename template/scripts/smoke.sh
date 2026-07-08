#!/usr/bin/env bash
# Script smoke — a fast syntax guard for the project's OWN shipped shell + python.
#
# Why: the git hooks and host-run scripts (.githooks/*, scripts/*.sh,
# backend/scripts/migrate.sh, …) are NOT exercised by the stack's Docker test
# suite. A stray quote in a hook silently disables commits; a broken migrate.sh
# only fails at deploy time. This catches those before they ship.
#
# No host SDK required (honours the no-host-SDK rule): it uses only bash + sh —
# already needed to run the hooks — and, IF python3 happens to be present, its
# stdlib py_compile. python3 is optional: absent, the .py sweep is skipped with a
# note, so this never forces a toolchain onto the host. CI runners have python3,
# so the check still runs there.
#
# Wire it into CI's "Tests" job and `make precommit`; run locally with `make smoke`.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
fail=0

# Directories to skip (vendored deps, build output, caches, throwaway profiles).
# One line, no backslash-newlines: it is expanded UNQUOTED into find's arg list.
prune='-name .git -o -name node_modules -o -name .dart_tool -o -name dist -o -name build -o -name out -o -name .next -o -name .venv -o -name __pycache__ -o -name .pytest_cache -o -name .auth'

# 1) Shell scripts → `bash -n`
while IFS= read -r f; do
  bash -n "$f" || { echo "✗ bash -n: $f"; fail=1; }
done < <(find . \( $prune \) -prune -o -name '*.sh' -type f -print)

# 2) Git hooks (POSIX sh, extensionless) → `sh -n`
if [ -d .githooks ]; then
  for h in .githooks/*; do
    [ -f "$h" ] || continue
    case "$h" in *.md) continue ;; esac   # skip .githooks/README.md
    sh -n "$h" || { echo "✗ sh -n: $h"; fail=1; }
  done
fi

# 3) Python → `py_compile` (only if python3 is on PATH; never a hard host dep)
if command -v python3 >/dev/null 2>&1; then
  while IFS= read -r f; do
    python3 -m py_compile "$f" || { echo "✗ py_compile: $f"; fail=1; }
  done < <(find . \( $prune \) -prune -o -name '*.py' -type f -print)
else
  echo "· python3 not found — skipping .py syntax sweep (CI runs it)."
fi

if [ "$fail" -eq 0 ]; then
  echo "✓ script smoke: shipped shell / hooks / python all parse cleanly"
fi
exit "$fail"
