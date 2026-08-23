#!/usr/bin/env bash
# Dependency-light behavioral tests for scripts/gate-selftest.sh.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../gate-selftest.sh"
TMP="$(mktemp -d)"
fail=0
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/backend" "$TMP/frontend" "$TMP/empty" "$TMP/bin" "$TMP/logs"

pass() { printf '  PASS %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1" >&2; fail=1; }
expect_contains() { # <output> <needle> <description>
  case "$1" in *"$2"*) pass "$3" ;; *) bad "$3" ;; esac
}
expect_absent() { # <output> <needle> <description>
  case "$1" in *"$2"*) bad "$3" ;; *) pass "$3" ;; esac
}

cat > "$TMP/bin/mapped" <<'RUNNER'
#!/usr/bin/env bash
host_dir="$1"
container_dir="$2"
shift 2
[ "${1:-}" = "sh" ] && [ "${2:-}" = "-c" ] || exit 64
command="${3//${container_dir}/${host_dir}}"
sh -c "$command"
RUNNER

cat > "$TMP/bin/dead" <<'RUNNER'
#!/usr/bin/env bash
echo "synthetic daemon unavailable" >&2
echo "API_TOKEN=synthetic-secret-value" >&2
echo "__RUNNER_OK__" >&2
exit 1
RUNNER

cat > "$TMP/bin/sighted-nonzero" <<'RUNNER'
#!/usr/bin/env bash
here="$(cd "$(dirname "$0")" && pwd)"
"$here/mapped" "$@"
exit 75
RUNNER

cat > "$TMP/bin/sighted-cleanup-fail" <<'RUNNER'
#!/usr/bin/env bash
host_dir="$1"
container_dir="$2"
shift 2
here="$(cd "$(dirname "$0")" && pwd)"
"$here/mapped" "$host_dir" "$container_dir" "$@" || exit $?
for probe in "$host_dir"/gate-selftest.*; do
  [ -f "$probe" ] || continue
  rm -f -- "$probe"
  mkdir -- "$probe"
  break
done
RUNNER

cat > "$TMP/bin/deleting-log" <<'RUNNER'
#!/usr/bin/env bash
rm -f -- "$TMPDIR"/gate-selftest-runner.*
echo "deleted private log under $TMPDIR" >&2
exit 77
RUNNER
chmod +x "$TMP/bin/mapped" "$TMP/bin/dead" "$TMP/bin/sighted-nonzero" "$TMP/bin/sighted-cleanup-fail" "$TMP/bin/deleting-log"

mkdir -p "$TMP/noop-bin"
cat > "$TMP/noop-bin/rm" <<'RUNNER'
#!/usr/bin/env bash
printf 'private cleanup arguments: %s\n' "$*"
exit 0
RUNNER
chmod +x "$TMP/noop-bin/rm"

mkdir -p "$TMP/noisy-grep-bin"
cat > "$TMP/noisy-grep-bin/grep" <<'RUNNER'
#!/usr/bin/env bash
printf 'private grep arguments: %s\n' "$*"
exit 1
RUNNER
chmod +x "$TMP/noisy-grep-bin/grep"

mkdir -p "$TMP/success-grep-bin"
cat > "$TMP/success-grep-bin/grep" <<'RUNNER'
#!/usr/bin/env bash
exit 0
RUNNER
chmod +x "$TMP/success-grep-bin/grep"

run_guard() { # <backend-host-dir> <frontend-runner...>
  local backend_dir="$1"
  shift
  (
    cd "$TMP" || exit 70
    TMPDIR="$TMP/logs" bash "$SCRIPT" \
      --case backend-tools backend /workspace "$TMP/bin/mapped" "$backend_dir" /workspace \
      --case frontend-tools frontend /workspace "$@"
  ) 2>&1
}

out="$(run_guard "$TMP/backend" "$TMP/bin/mapped" "$TMP/frontend" /workspace)"
rc=$?
if [ "$rc" -eq 0 ]; then pass "sighted runners exit zero"; else bad "sighted runners exit zero"; fi
expect_contains "$out" "backend-tools grades the working tree" "backend source is observed"
expect_contains "$out" "frontend-tools grades the working tree" "frontend source is observed"

# Mutation model: removing a bind mount maps the container path to an empty
# directory. The runner still starts, so this must be classified as BLIND.
out="$(run_guard "$TMP/empty" "$TMP/bin/mapped" "$TMP/frontend" /workspace)"
rc=$?
if [ "$rc" -ne 0 ]; then pass "removed-mount mutation exits non-zero"; else bad "removed-mount mutation exits non-zero"; fi
expect_contains "$out" "backend-tools CANNOT see the working tree" "removed mount is diagnosed as stale source"
expect_contains "$out" "frontend-tools grades the working tree" "all configured cases still run after a failure"
expect_absent "$out" "backend-tools RUNNER FAILED" "blind runner is not misreported as infrastructure"

out="$(run_guard "$TMP/backend" "$TMP/bin/dead")"
rc=$?
if [ "$rc" -ne 0 ]; then pass "dead runner exits non-zero"; else bad "dead runner exits non-zero"; fi
expect_contains "$out" "frontend-tools RUNNER FAILED" "dead runner is diagnosed as infrastructure"
expect_contains "$out" "container runtime unavailable" "privacy-safe runner category is surfaced"
expect_absent "$out" "synthetic-secret-value" "runner secret values are never logged"
expect_absent "$out" "API_TOKEN=" "runner secret assignments are never logged"
expect_absent "$out" "frontend-tools CANNOT see the working tree" "dead runner is never reported as blind"

# Fixed legacy marker text from runner stderr must not spoof the unique token.
expect_contains "$out" "source visibility is UNKNOWN" "runner marker spoof does not forge a verdict"

out="$(run_guard "$TMP/backend" "$TMP/bin/deleting-log")"
rc=$?
if [ "$rc" -ne 0 ]; then pass "deleted private log exits non-zero"; else bad "deleted private log exits non-zero"; fi
expect_contains "$out" "frontend-tools RUNNER FAILED" "deleted private log fails closed"
expect_contains "$out" "runner produced no output" "deleted private log uses a fixed category"
expect_absent "$out" "$TMP" "deleted private log never exposes its host path"

out="$(run_guard "$TMP/backend" "$TMP/bin/sighted-nonzero" "$TMP/frontend" /workspace)"
rc=$?
if [ "$rc" -ne 0 ]; then pass "sighted-but-nonzero runner exits non-zero"; else bad "sighted-but-nonzero runner exits non-zero"; fi
expect_contains "$out" "frontend-tools RUNNER FAILED" "non-zero wrapper invalidates visible markers"
expect_contains "$out" "visibility OBSERVED" "non-zero wrapper preserves the marker observation"
expect_absent "$out" "frontend-tools grades the working tree" "non-zero wrapper is never accepted as green"
expect_absent "$out" "frontend-tools CANNOT see the working tree" "non-zero wrapper is not misreported as blind"

out="$(
  cd "$TMP" && bash "$SCRIPT" \
    --case cleanup-failure backend /workspace "$TMP/bin/sighted-cleanup-fail" "$TMP/backend" /workspace 2>&1
)"
rc=$?
if [ "$rc" -eq 2 ]; then pass "cleanup failure overrides a sighted probe"; else bad "cleanup failure overrides a sighted probe"; fi
expect_contains "$out" "cleanup failed; private temporary data may remain" "cleanup failure uses a fixed private diagnostic"
expect_absent "$out" "$TMP" "cleanup failure never logs a host path"
expect_absent "$out" "every Docker gate sees current source" "cleanup failure never reports aggregate green"
for leftover in "$TMP/backend"/gate-selftest.*; do
  [ ! -d "$leftover" ] || rm -rf -- "$leftover"
done

out="$(cd "$TMP" && PATH="$TMP/noop-bin:$PATH" TMPDIR="$TMP/logs" bash "$SCRIPT" \
  --case noop-cleanup backend /workspace "$TMP/bin/mapped" "$TMP/backend" /workspace 2>&1)"
rc=$?
if [ "$rc" -eq 2 ]; then pass "lying rm cannot forge cleanup success"; else bad "lying rm cannot forge cleanup success"; fi
expect_contains "$out" "cleanup failed; private temporary data may remain" "lying rm produces a fixed cleanup diagnostic"
expect_absent "$out" "$TMP" "lying rm never exposes a host path"
expect_absent "$out" "private cleanup arguments" "lying rm stdout is never exposed"
expect_absent "$out" "every Docker gate sees current source" "lying rm never reports aggregate green"
for leftover in "$TMP/backend"/gate-selftest.* "$TMP/logs"/gate-selftest-runner.*; do
  if [ -e "$leftover" ] || [ -L "$leftover" ]; then /bin/rm -f -- "$leftover"; fi
done

out="$(cd "$TMP" && PATH="$TMP/noisy-grep-bin:$PATH" TMPDIR="$TMP/logs" bash "$SCRIPT" \
  --case noisy-grep backend /workspace "$TMP/bin/mapped" "$TMP/backend" /workspace 2>&1)"
rc=$?
if [ "$rc" -eq 0 ]; then pass "noisy grep cannot alter marker evidence"; else bad "noisy grep cannot alter marker evidence"; fi
expect_contains "$out" "every Docker gate sees current source" "marker decision uses Bash built-ins"
expect_absent "$out" "$TMP" "lying grep never exposes a host path"
expect_absent "$out" "private grep arguments" "lying grep stdout is never exposed"

out="$(cd "$TMP" && PATH="$TMP/success-grep-bin:$PATH" TMPDIR="$TMP/logs" bash "$SCRIPT" \
  --case success-lying-grep backend /workspace "$TMP/bin/mapped" "$TMP/empty" /workspace 2>&1)"
rc=$?
if [ "$rc" -ne 0 ]; then pass "success-lying grep cannot forge visibility"; else bad "success-lying grep cannot forge visibility"; fi
expect_contains "$out" "CANNOT see the working tree" "blind evidence remains blind without grep trust"
expect_absent "$out" "every Docker gate sees current source" "success-lying grep never reports aggregate green"

cat > "$TMP/bin/blind-nonzero" <<'RUNNER'
#!/usr/bin/env bash
here="$(cd "$(dirname "$0")" && pwd)"
"$here/mapped" "$@"
exit 76
RUNNER
chmod +x "$TMP/bin/blind-nonzero"
out="$(run_guard "$TMP/empty" "$TMP/bin/blind-nonzero" "$TMP/empty" /workspace)"
rc=$?
if [ "$rc" -ne 0 ]; then pass "blind-and-nonzero runner exits non-zero"; else bad "blind-and-nonzero runner exits non-zero"; fi
expect_contains "$out" "frontend-tools CANNOT see the working tree" "non-zero wrapper preserves a blind observation"
expect_contains "$out" "frontend-tools RUNNER FAILED after the visibility probe" "blind non-zero wrapper also reports runner failure"

leftovers="$(find "$TMP/backend" "$TMP/frontend" "$TMP/empty" -name 'gate-selftest.*' -print | wc -l | tr -d ' ')"
if [ "$leftovers" = "0" ]; then pass "sentinels are cleaned in pass/fail modes"; else bad "sentinels are cleaned in pass/fail modes"; fi
logs="$(find "$TMP/logs" -name 'gate-selftest-runner.*' -print | wc -l | tr -d ' ')"
if [ "$logs" = "0" ]; then pass "private runner logs are cleaned in pass/fail modes"; else bad "private runner logs are cleaned in pass/fail modes"; fi

out="$(cd "$TMP" && bash "$SCRIPT" --case invalid backend relative "$TMP/bin/dead" 2>&1)"
rc=$?
if [ "$rc" -eq 2 ]; then pass "invalid configuration fails closed"; else bad "invalid configuration fails closed"; fi
expect_contains "$out" "container directory must be absolute" "invalid configuration is actionable"

out="$(
  cd "$TMP" && bash "$SCRIPT" \
    --case invalid backend relative "$TMP/bin/dead" \
    --case dead frontend /workspace "$TMP/bin/dead" 2>&1
)"
rc=$?
if [ "$rc" -eq 2 ]; then pass "configuration failure outranks later runtime failure"; else bad "configuration failure outranks later runtime failure"; fi

if [ "$fail" -eq 0 ]; then
  echo "gate-selftest guard self-test: ALL PASS"
else
  echo "gate-selftest guard self-test: FAILURES" >&2
fi
exit "$fail"
