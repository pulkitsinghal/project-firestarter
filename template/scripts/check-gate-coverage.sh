#!/usr/bin/env bash
# Gate-coverage tripwire: a test suite the gate does not name cannot exist.
#
# A gate can run, see current source, drive the shipped artifact, and match
# released bytes — and still be green because it was pointed at four of six test
# suites. A suite nobody runs does not fail; it is invisible. This check closes
# that hole one level above every other gate: it DISCOVERS every test-root
# directory under the project and fails closed on any that no runner names.
#
# The declared roots are passed as arguments (the stack Makefile's TEST_SUITES).
# Discovery is self-enumerating on purpose — a hand-maintained list of suites
# decays exactly like a hand-maintained list of checks — so the script finds the
# directories and the declaration only says which runner owns each one.
#
# Report discipline matches repo-hygiene.sh: a fixed rule ID and the offending
# directory paths the fix needs, never file contents.
#
# Usage: scripts/check-gate-coverage.sh [DECLARED_ROOT ...]
#   exit 0  every discovered test root is declared
#   exit 1  a discovered test root is undeclared (an unlisted suite)
#   exit 2  infrastructure error (missing tool, unusable tree)

set +x
set -uo pipefail
export LC_ALL=C

infra_error() {
  echo "check-gate-coverage: ERROR code=$1" >&2
  exit 2
}

for required_tool in find sort sed grep printf; do
  command -v "$required_tool" >/dev/null 2>&1 || infra_error "missing-tool"
done

# Discover test-root directories named test, tests, or __tests__. VCS, build,
# and vendor directories are pruned so a dependency's bundled tests never count
# as this project's suite. `|| true` keeps a permission-denied on some unrelated
# subtree from being read as a discovery failure under pipefail.
discovered=$(
  { find . \
      \( -name .git -o -name node_modules -o -name .dart_tool -o -name build \
         -o -name dist -o -name .next -o -name coverage -o -name .venv \
         -o -name __pycache__ -o -name vendor -o -name target \) -prune -o \
      -type d \( -name tests -o -name test -o -name __tests__ \) -print \
      2>/dev/null || true; } \
    | sed 's|^\./||' | sort -u
)

# Declared roots, normalized the same way (strip a leading ./ and trailing /).
declared=$(printf '%s\n' "$@" | sed 's|^\./||; s|/$||; /^$/d' | sort -u)

unlisted=""
count=0
while IFS= read -r root; do
  [ -n "$root" ] || continue
  count=$((count + 1))
  if ! printf '%s\n' "$declared" | grep -Fxq -- "$root"; then
    unlisted="${unlisted}${root}
"
  fi
done <<EOF
$discovered
EOF

if [ -n "$unlisted" ]; then
  echo "check-gate-coverage: FAIL rule=gate-coverage:unlisted-suite" >&2
  echo "unlisted test-root director(ies); wire each into a runner and add it to TEST_SUITES in the stack Makefile:" >&2
  printf '%s' "$unlisted" | sed '/^$/d; s/^/    /' >&2
  exit 1
fi

echo "check-gate-coverage: $count test-root(s) discovered, none unlisted"
exit 0
