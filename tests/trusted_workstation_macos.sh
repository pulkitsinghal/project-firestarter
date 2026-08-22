#!/usr/bin/env bash
# Native macOS status-wrapper behavior gate. Writes only under a disposable root.
set -eu

if [ "$(uname -s)" != Darwin ]; then
  printf 'macOS trusted-workstation behavior: SKIP (not Darwin)\n'
  exit 0
fi

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
FIXTURE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/firestarter-trusted-workstation.XXXXXX")"
RUNTIME="$FIXTURE_ROOT/runtime"
REPOSITORY='Example-Org/sample-repo'
PASSED=0

cleanup() { rm -rf -- "$FIXTURE_ROOT"; }
trap cleanup EXIT HUP INT TERM

cp -R "$REPO_ROOT/addons/trusted_workstation/common" "$RUNTIME"
printf '%s\n' "$REPOSITORY" > "$RUNTIME/trusted-workstation/repository.txt"
STATUS="$RUNTIME/scripts/trusted-workstation-status.sh"
CORPUS="$REPO_ROOT/tests/fixtures/trusted_workstation_ledgers"
TEST_HOME="$FIXTURE_ROOT/home"
DEFAULT_DIR="$TEST_HOME/Library/Application Support/Firestarter/trusted-workstation/Example-Org--sample-repo"
mkdir -p "$DEFAULT_DIR" "$FIXTURE_ROOT/ledgers"

sha256() { /usr/bin/shasum -a 256 -- "$1" | /usr/bin/awk '{print $1}'; }
assert_output_safe() {
  output=$1
  [ "${#output}" -le 512 ] || { printf 'unbounded output\n' >&2; exit 1; }
  if printf '%s' "$output" | LC_ALL=C grep -q '[[:cntrl:]]'; then
    printf 'terminal control output\n' >&2; exit 1
  fi
}
invoke_immutable() {
  ledger=$1; shift
  before=$(sha256 "$ledger")
  output_file="$FIXTURE_ROOT/output"
  set +e
  HOME="$TEST_HOME" TRUSTED_WORKSTATION_LEDGER= "$STATUS" "$@" >"$output_file" 2>&1
  code=$?
  set -e
  output=$(tr -d '\r\n' < "$output_file")
  after=$(sha256 "$ledger")
  [ "$before" = "$after" ] || { printf 'ledger mutated\n' >&2; exit 1; }
  assert_output_safe "$output"
  INVOKE_CODE=$code
  INVOKE_OUTPUT=$output
}

cp "$CORPUS/accepted/blocked.json" "$DEFAULT_DIR/ledger.json"
invoke_immutable "$DEFAULT_DIR/ledger.json"
[ "$INVOKE_CODE" -eq 0 ] || { printf 'default path failed: %s\n' "$INVOKE_OUTPUT" >&2; exit 1; }
PASSED=$((PASSED + 1))

explicit="$FIXTURE_ROOT/ledgers/explicit.json"
cp "$CORPUS/accepted/sync-enabled.json" "$explicit"
invoke_immutable "$explicit" --ledger "$explicit"
[ "$INVOKE_CODE" -eq 0 ] || { printf 'explicit path failed: %s\n' "$INVOKE_OUTPUT" >&2; exit 1; }
PASSED=$((PASSED + 1))

for args in '--ledger' '--unknown value' '--ledger value extra'; do
  # shellcheck disable=SC2086 -- intentional argument-count fixtures
  set +e
  HOME="$TEST_HOME" "$STATUS" $args >"$FIXTURE_ROOT/output" 2>&1
  code=$?
  set -e
  output=$(tr -d '\r\n' < "$FIXTURE_ROOT/output")
  [ "$code" -eq 2 ] || { printf 'argument handling returned %s\n' "$code" >&2; exit 1; }
  assert_output_safe "$output"
  PASSED=$((PASSED + 1))
done

target="$FIXTURE_ROOT/target"
mkdir -p "$target"
cp "$CORPUS/accepted/blocked.json" "$target/ledger.json"
ln -s "$target" "$FIXTURE_ROOT/linked-parent"
invoke_immutable "$target/ledger.json" --ledger "$FIXTURE_ROOT/linked-parent/ledger.json"
[ "$INVOKE_CODE" -eq 1 ] && printf '%s' "$INVOKE_OUTPUT" | grep -q 'link' || {
  printf 'symlink parent was not rejected: %s\n' "$INVOKE_OUTPUT" >&2; exit 1;
}
PASSED=$((PASSED + 1))

rejected="$FIXTURE_ROOT/ledgers/rejected.json"
cp "$CORPUS/rejected/unknown-field.json" "$rejected"
invoke_immutable "$rejected" --ledger "$rejected"
[ "$INVOKE_CODE" -eq 1 ] || { printf 'validator exit was not propagated: %s\n' "$INVOKE_OUTPUT" >&2; exit 1; }
PASSED=$((PASSED + 1))

for ledger in "$CORPUS/accepted"/*.json; do
  invoke_immutable "$ledger" --ledger "$ledger"
  [ "$INVOKE_CODE" -eq 0 ] || { printf 'accepted corpus rejected: %s\n' "$INVOKE_OUTPUT" >&2; exit 1; }
  PASSED=$((PASSED + 1))
done
for ledger in "$CORPUS/rejected"/*.json; do
  invoke_immutable "$ledger" --ledger "$ledger"
  [ "$INVOKE_CODE" -eq 1 ] || { printf 'rejected corpus accepted: %s\n' "$INVOKE_OUTPUT" >&2; exit 1; }
  PASSED=$((PASSED + 1))
done

printf 'macOS trusted-workstation behavior: PASS (%s cases)\n' "$PASSED"
