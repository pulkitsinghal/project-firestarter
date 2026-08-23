#!/usr/bin/env bash
# Prove Docker-backed gates grade the current working tree, not a stale image.
#
# Each --case supplies a diagnostic label, host source directory, matching
# container directory, and the exact runner argv used by the real Make target:
#
#   gate-selftest.sh --case LABEL HOST_DIR CONTAINER_DIR RUNNER [ARGS...] \
#                    [--case ...]
#
# The runner receives `sh -c <probe>` after its configured arguments. A unique
# control token proves the container shell actually started; a second token is
# emitted only when that shell sees the sentinel planted in HOST_DIR. Keeping
# those observations distinct prevents Docker/runner failures from being
# misreported as stale-source blindness.

set -uo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: gate-selftest.sh --case LABEL HOST_DIR CONTAINER_DIR RUNNER [ARGS...] [--case ...]
USAGE
}

status=0
blind_error=0
runner_error=0
case_count=0
# Bash 3.2 + nounset rejects expansion of a truly empty array. Keep one inert
# element so cleanup is portable on the required macOS shell.
created=("")
cleanup_failure=0
pending_signal=0
temp_attempt=0
umask 077

remove_private() { # <path>
  # Catchable process-group cancellation must not kill the unlink subprocess.
  # The parent still records/replays the signal and reports its signal status.
  if ! (
    trap '' HUP INT TERM
    command rm -f -- "$1" >/dev/null 2>&1
  ); then
    return 1
  fi
  [ ! -e "$1" ] && [ ! -L "$1" ]
}

cleanup_files() {
  local path failed=0
  for path in "${created[@]}"; do
    [ -n "$path" ] || continue
    remove_private "$path" || failed=1
  done
  return "$failed"
}
# Called indirectly by the EXIT trap below.
# shellcheck disable=SC2329
exit_cleanup() { # <prior-status>
  local prior="$1" final
  # Install deferring handlers before removing EXIT so a second signal cannot
  # interrupt deletion and strand a sentinel/private log.
  defer_signal_traps
  trap - EXIT
  if ! cleanup_files; then
    cleanup_failure=1
  fi
  final="$prior"
  if [ "$cleanup_failure" -ne 0 ]; then
    echo "✗ gate self-test cleanup failed; private temporary data may remain" >&2
    final=2
  elif [ "$pending_signal" -ne 0 ] && [ "$prior" -eq 0 ]; then
    final="$pending_signal"
  fi
  exit "$final"
}
# Called indirectly by the signal traps below.
# shellcheck disable=SC2329
on_signal() { # <portable 128+signal exit>
  # Keep later catchable signals deferred while EXIT cleanup runs.
  defer_signal_traps
  exit "$1"
}
arm_signal_traps() {
  trap 'on_signal 129' HUP
  trap 'on_signal 130' INT
  trap 'on_signal 143' TERM
}
# Called indirectly by the deferred signal traps below.
# shellcheck disable=SC2329
remember_signal() { # <portable 128+signal exit>; used during temp creation
  [ "$pending_signal" -ne 0 ] || pending_signal="$1"
}
defer_signal_traps() {
  trap 'remember_signal 129' HUP
  trap 'remember_signal 130' INT
  trap 'remember_signal 143' TERM
}
trap 'exit_cleanup "$?"' EXIT
arm_signal_traps

tracked_temp=""
create_tracked_temp() { # <XXXXXX-template>; sets tracked_temp
  local template="$1" prefix candidate tries=0
  case "$template" in
    *XXXXXX) prefix="${template%XXXXXX}" ;;
    *) return 1 ;;
  esac
  # Create in this shell with noclobber, so the candidate pathname is known
  # before creation. Deferred traps cannot strand a child-created unnamed file.
  pending_signal=0
  defer_signal_traps
  while [ "$tries" -lt 100 ]; do
    tries=$((tries + 1))
    temp_attempt=$((temp_attempt + 1))
    candidate="${prefix}$$-${RANDOM:-0}-$temp_attempt"
    set -C
    if : 2>/dev/null > "$candidate"; then
      set +C
      tracked_temp="$candidate"
      created+=("$tracked_temp")
      arm_signal_traps
      if [ "$pending_signal" -ne 0 ]; then
        on_signal "$pending_signal"
      fi
      return 0
    fi
    set +C
    if [ "$pending_signal" -ne 0 ]; then break; fi
  done
  arm_signal_traps
  if [ "$pending_signal" -ne 0 ]; then
    on_signal "$pending_signal"
  fi
  return 1
}

mark_runtime_failure() {
  # Configuration failure (2) remains the strongest fail-closed status even if
  # a later, valid case also observes a runtime failure.
  [ "$status" -eq 2 ] || status=1
}

has_exact_line() { # <file> <line>
  local line
  [ -r "$1" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    [ "$line" != "$2" ] || return 0
  done 2>/dev/null < "$1"
  return 1
}

show_runner_summary() { # <captured-output-file> <exit-code>
  local category="runner detail withheld; rerun the labeled target in a private terminal"
  if [ ! -s "$1" ]; then
    category="runner produced no output"
  elif grep -Eqi 'cannot connect.*daemon|daemon unavailable|container runtime unavailable' "$1" >/dev/null 2>&1; then
    category="container runtime unavailable"
  elif grep -Eqi 'validating .*compose|services\..*must be|configuration[^[:alnum:]]+invalid|invalid[^[:alnum:]]+configuration' "$1" >/dev/null 2>&1; then
    category="container configuration invalid"
  elif grep -Eqi 'pull access denied|requested access.*denied|unauthorized.*(image|registry)' "$1" >/dev/null 2>&1; then
    category="image pull or registry access failed"
  elif grep -Eqi 'no space left|disk[^[:alnum:]]+full' "$1" >/dev/null 2>&1; then
    category="runner storage exhausted"
  elif grep -Eqi 'permission denied|operation not permitted' "$1" >/dev/null 2>&1; then
    category="runner permission denied"
  elif grep -Eqi 'failed to solve|build[^[:alnum:]]+failed|executor failed' "$1" >/dev/null 2>&1; then
    category="image build failed"
  fi
  # Never echo runner-controlled bytes: build/daemon stderr may contain secret
  # assignments, registry credentials, private paths, or project details.
  printf '      | runner exit=%s; %s\n' "$2" "$category" >&2
}

check_case() { # <label> <host-dir> <container-dir> <runner argv...>
  local label="$1" host_dir="$2" container_dir="$3"
  shift 3
  local -a runner=("$@")
  local probe probe_name nonce runner_marker seen_marker command runner_log runner_rc

  if [ ! -d "$host_dir" ]; then
    echo "✗ gate self-test configuration: source directory is missing for $label" >&2
    status=2
    return
  fi
  case "$container_dir" in
    /*) ;;
    *)
      echo "✗ gate self-test configuration: container directory must be absolute for $label" >&2
      status=2
      return ;;
  esac
  case "$container_dir" in
    *"'"*|*$'\n'*|*$'\r'*)
      echo "✗ gate self-test configuration: unsupported container directory for $label" >&2
      status=2
      return ;;
  esac
  if [ "${#runner[@]}" -eq 0 ]; then
    echo "✗ gate self-test configuration: runner is missing for $label" >&2
    status=2
    return
  fi

  if ! create_tracked_temp "$host_dir/gate-selftest.XXXXXX"; then
    echo "✗ gate self-test configuration: cannot create a sentinel for $label" >&2
    status=2
    return
  fi
  probe="$tracked_temp"
  if ! create_tracked_temp "${TMPDIR:-/tmp}/gate-selftest-runner.XXXXXX"; then
    remove_private "$probe" || cleanup_failure=1
    echo "✗ gate self-test configuration: cannot create a private runner log for $label" >&2
    status=2
    return
  fi
  runner_log="$tracked_temp"
  probe_name="${probe##*/}"
  case_count=$((case_count + 1))
  nonce="$$-${RANDOM:-0}-$case_count"
  runner_marker="__FIRESTARTER_RUNNER_OK_${nonce}__"
  seen_marker="__FIRESTARTER_SENTINEL_SEEN_${nonce}__"
  command="printf '%s\\n' '$runner_marker'; if test -f '${container_dir%/}/$probe_name'; then printf '%s\\n' '$seen_marker'; fi; :"

  if "${runner[@]}" sh -c "$command" >"$runner_log" 2>&1; then
    runner_rc=0
  else
    runner_rc=$?
  fi
  remove_private "$probe" || cleanup_failure=1

  # Marker evidence and wrapper health are independent facts. Preserve the
  # visibility observation even when Compose later exits non-zero, but never
  # accept a non-zero wrapper as green.
  if ! has_exact_line "$runner_log" "$runner_marker"; then
    echo "  ✗ $label RUNNER FAILED — source visibility is UNKNOWN" >&2
    show_runner_summary "$runner_log" "$runner_rc"
    runner_error=1
    mark_runtime_failure
  elif has_exact_line "$runner_log" "$seen_marker"; then
    if [ "$runner_rc" -eq 0 ]; then
      echo "  ✓ $label grades the working tree"
    else
      echo "  ✗ $label RUNNER FAILED after observing current source — visibility OBSERVED" >&2
      show_runner_summary "$runner_log" "$runner_rc"
      runner_error=1
      mark_runtime_failure
    fi
  else
    echo "  ✗ $label CANNOT see the working tree — it is grading STALE source" >&2
    blind_error=1
    mark_runtime_failure
    if [ "$runner_rc" -ne 0 ]; then
      echo "  ✗ $label RUNNER FAILED after the visibility probe" >&2
      show_runner_summary "$runner_log" "$runner_rc"
      runner_error=1
    fi
  fi
  remove_private "$runner_log" || cleanup_failure=1
}

if [ "$#" -eq 0 ]; then
  usage
  exit 2
fi

echo "→ gate self-test (Docker gates must grade the current working tree)"
while [ "$#" -gt 0 ]; do
  if [ "$1" != "--case" ] || [ "$#" -lt 5 ]; then
    usage
    exit 2
  fi
  shift
  label="$1"
  host_dir="$2"
  container_dir="$3"
  shift 3
  runner=()
  while [ "$#" -gt 0 ] && [ "$1" != "--case" ]; do
    runner+=("$1")
    shift
  done
  check_case "$label" "$host_dir" "$container_dir" "${runner[@]}"
done

if [ "$blind_error" -ne 0 ]; then
  cat >&2 <<'BLIND'

✗ At least one Docker gate is BLIND.

  A blind gate can report green while grading old source. Restore the live
  source bind mount, or make the exact runner rebuild the current build context
  before every gate. Do not silence this check.
BLIND
fi

if [ "$runner_error" -ne 0 ]; then
  cat >&2 <<'RUNNER'

✗ At least one Docker gate RUNNER failed or exited non-zero.

  This is infrastructure/build failure, not proof of stale source. A fixed,
  privacy-safe category is above; rerun the labeled target in a private terminal
  for details, repair it, and retry. Do not report BLIND unless the container
  actually starts and fails to observe the sentinel.
RUNNER
fi

if ! cleanup_files; then cleanup_failure=1; fi
if [ "$cleanup_failure" -ne 0 ]; then status=2; fi
created=("")
trap - EXIT
if [ "$cleanup_failure" -ne 0 ]; then
  echo "✗ gate self-test cleanup failed; private temporary data may remain" >&2
fi

if [ "$status" -eq 0 ]; then
  echo "✓ gate self-test: every Docker gate sees current source"
fi
exit "$status"
