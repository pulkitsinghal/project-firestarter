#!/usr/bin/env bash
# Optional, content-suppressed mutation proof for project-owned guarantees.
# It snapshots current bytes (never Git), requires a green focused baseline,
# applies one exact literal replacement, requires one declared failure status,
# and restores exactly. A private journal handles interrupted-process recovery.

set +x
set -uo pipefail
set -f
export LC_ALL=C
umask 077

if [ "$#" -ne 0 ]; then
  echo "usage: scripts/mutation-check.sh" >&2
  exit 2
fi
command -v bash >/dev/null 2>&1 || exit 2
command -v dirname >/dev/null 2>&1 || {
  echo "mutation-check: ERROR code=missing-basic-tool" >&2
  exit 2
}

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P) || {
  echo "mutation-check: ERROR code=script-location" >&2
  exit 2
}
repo_root=$(cd "$script_dir/.." 2>/dev/null && pwd -P) || {
  echo "mutation-check: ERROR code=script-location" >&2
  exit 2
}
cd "$repo_root" 2>/dev/null || {
  echo "mutation-check: ERROR code=script-location" >&2
  exit 2
}
cases_file="$script_dir/mutation-cases.sh"
[ -f "$cases_file" ] && [ ! -L "$cases_file" ] || {
  echo "mutation-check: ERROR code=cases-file" >&2
  exit 2
}
if ! bash -n "$cases_file" >/dev/null 2>&1; then
  echo "mutation-check: ERROR code=cases-syntax" >&2
  exit 2
fi

timeout_seconds=${MUTATION_TIMEOUT_SECONDS:-300}
case "$timeout_seconds" in ''|*[!0-9]*)
  echo "mutation-check: ERROR code=timeout-config" >&2; exit 2 ;;
esac
if [ "$timeout_seconds" -lt 1 ] || [ "$timeout_seconds" -gt 3600 ]; then
  echo "mutation-check: ERROR code=timeout-config" >&2
  exit 2
fi

runtime_ready=0
hash_tool=
stat_mode=
temp_root=
lock_dir="$repo_root/.mutation-check.lock"
lock_owned=0
preserve_lock=0
active_target=
active_relative=
active_original_hash=
active_mutated_hash=
active_test_pgid=
active_watchdog_pid=
case_total=0
killed_total=0
survived_total=0
infra_total=0
abort_run=0
label_regex='^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$'

hash_file() {
  if [ "$hash_tool" = sha256sum ]; then
    sha256sum "$1" 2>/dev/null | awk '{print $1}'
  else
    shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
  fi
}

validate_relative_path() {
  candidate=$1
  case "$candidate" in
    ''|/*|./*|*/|*//*|*\\*|*$'\n'*|*$'\r'*|*$'\t'*) return 1 ;;
  esac
  saved_ifs=$IFS
  IFS=/
  cursor=$repo_root
  for component in $candidate; do
    case "$component" in ''|.|..) IFS=$saved_ifs; return 1 ;; esac
    cursor="$cursor/$component"
    [ ! -L "$cursor" ] || { IFS=$saved_ifs; return 1; }
  done
  IFS=$saved_ifs
  [ -f "$cursor" ] && [ ! -L "$cursor" ]
}

validate_parent_path() {
  candidate=$1
  parent_relative=${candidate%/*}
  [ "$parent_relative" != "$candidate" ] || parent_relative=
  saved_ifs=$IFS
  IFS=/
  cursor=$repo_root
  for component in $parent_relative; do
    case "$component" in ''|.|..) IFS=$saved_ifs; return 1 ;; esac
    cursor="$cursor/$component"
    [ -d "$cursor" ] && [ ! -L "$cursor" ] \
      || { IFS=$saved_ifs; return 1; }
  done
  IFS=$saved_ifs
}

link_count() {
  if [ "$stat_mode" = gnu ]; then
    stat -c %h "$1" 2>/dev/null
  else
    stat -f %l "$1" 2>/dev/null
  fi
}

journal_read() {
  journal_value=
  [ -f "$lock_dir/$1" ] && [ ! -L "$lock_dir/$1" ] || return 1
  IFS= read -r journal_value < "$lock_dir/$1" || return 1
}

journal_write() {
  printf '%s\n' "$2" > "$lock_dir/$1" 2>/dev/null
}

terminate_active_test() {
  if [ -n "$active_watchdog_pid" ]; then
    kill -TERM -- "-$active_watchdog_pid" >/dev/null 2>&1 || true
    wait "$active_watchdog_pid" >/dev/null 2>&1 || true
    active_watchdog_pid=
  fi
  if [ -n "$active_test_pgid" ]; then
    kill -TERM -- "-$active_test_pgid" >/dev/null 2>&1 || true
    grace=0
    while kill -0 -- "-$active_test_pgid" >/dev/null 2>&1 \
      && [ "$grace" -lt 2 ]; do
      sleep 1
      grace=$((grace + 1))
    done
    kill -KILL -- "-$active_test_pgid" >/dev/null 2>&1 || true
    wait "$active_test_pgid" >/dev/null 2>&1 || true
    active_test_pgid=
  fi
}

restore_active() {
  [ -n "$active_target" ] || return 0
  terminate_active_test
  validate_parent_path "$active_relative" || return 1
  [ -f "$lock_dir/original" ] && [ ! -L "$lock_dir/original" ] || return 1
  backup_hash=$(hash_file "$lock_dir/original") || return 1
  [ "$backup_hash" = "$active_original_hash" ] || return 1
  if [ -e "$active_target" ] || [ -L "$active_target" ]; then
    [ -f "$active_target" ] && [ ! -L "$active_target" ] || return 1
    current_hash=$(hash_file "$active_target") || return 1
    if [ "$current_hash" != "$active_original_hash" ] \
      && [ "$current_hash" != "$active_mutated_hash" ]; then
      journal_write state drift || true
      preserve_lock=1
      return 1
    fi
  fi
  journal_write state restoring || return 1
  rm -f "$active_target" >/dev/null 2>&1 || return 1
  cp -p "$lock_dir/original" "$active_target" >/dev/null 2>&1 || return 1
  restored_hash=$(hash_file "$active_target") || return 1
  [ "$restored_hash" = "$active_original_hash" ] || return 1
  journal_write state idle || return 1
  rm -f "$lock_dir/original" "$lock_dir/target" \
    "$lock_dir/original_hash" "$lock_dir/mutated_hash" \
    "$lock_dir/child_pgid" >/dev/null 2>&1 || return 1
  active_target=
  active_relative=
  active_original_hash=
  active_mutated_hash=
}

recover_stale_lock() {
  [ -d "$lock_dir" ] && [ ! -L "$lock_dir" ] || return 1
  journal_read state || return 1
  recovery_state=$journal_value
  case "$recovery_state" in
    idle) rm -rf "$lock_dir" >/dev/null 2>&1; return $? ;;
    prepared|mutated|restoring|drift) ;;
    *) return 1 ;;
  esac
  journal_read target || return 1
  recovery_relative=$journal_value
  journal_read original_hash || return 1
  recovery_original_hash=$journal_value
  [ -f "$lock_dir/original" ] && [ ! -L "$lock_dir/original" ] || return 1
  recovery_backup_hash=$(hash_file "$lock_dir/original") || return 1
  [ "$recovery_backup_hash" = "$recovery_original_hash" ] || return 1
  validate_parent_path "$recovery_relative" || return 1
  recovery_target="$repo_root/$recovery_relative"
  if journal_read child_pgid; then
    recovery_child=$journal_value
    case "$recovery_child" in ''|*[!0-9]*) return 1 ;; esac
    if kill -0 -- "-$recovery_child" >/dev/null 2>&1; then return 1; fi
  fi
  if [ -e "$recovery_target" ] || [ -L "$recovery_target" ]; then
    [ -f "$recovery_target" ] && [ ! -L "$recovery_target" ] || return 1
    recovery_current_hash=$(hash_file "$recovery_target") || return 1
    if [ "$recovery_current_hash" = "$recovery_original_hash" ]; then
      rm -rf "$lock_dir" >/dev/null 2>&1
      return $?
    fi
    [ "$recovery_state" != drift ] || return 1
    journal_read mutated_hash || return 1
    recovery_mutated_hash=$journal_value
    [ "$recovery_current_hash" = "$recovery_mutated_hash" ] || return 1
  elif [ "$recovery_state" = drift ]; then
    return 1
  fi
  rm -f "$recovery_target" >/dev/null 2>&1 || return 1
  cp -p "$lock_dir/original" "$recovery_target" >/dev/null 2>&1 || return 1
  recovery_current_hash=$(hash_file "$recovery_target") || return 1
  [ "$recovery_current_hash" = "$recovery_original_hash" ] || return 1
  rm -rf "$lock_dir" >/dev/null 2>&1
}

acquire_lock() {
  if mkdir "$lock_dir" 2>/dev/null; then
    :
  else
    [ -d "$lock_dir" ] && [ ! -L "$lock_dir" ] || return 1
    lock_pid=
    if journal_read owner; then lock_pid=$journal_value; fi
    case "$lock_pid" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$lock_pid" >/dev/null 2>&1 && return 1
    recover_stale_lock || return 2
    mkdir "$lock_dir" 2>/dev/null || return 1
  fi
  journal_write owner "$$" || {
    rm -rf "$lock_dir" >/dev/null 2>&1
    return 1
  }
  journal_write state idle || {
    rm -rf "$lock_dir" >/dev/null 2>&1
    return 1
  }
  lock_owned=1
}

init_runtime() {
  [ "$runtime_ready" -eq 0 ] || return 0
  for required_tool in awk cmp cp dd grep mktemp mkdir mv rm sleep stat wc; do
    command -v "$required_tool" >/dev/null 2>&1 || return 1
  done
  if command -v sha256sum >/dev/null 2>&1; then hash_tool=sha256sum
  elif command -v shasum >/dev/null 2>&1; then hash_tool=shasum
  else return 1
  fi
  if stat -c %h "$cases_file" >/dev/null 2>&1; then stat_mode=gnu
  elif stat -f %l "$cases_file" >/dev/null 2>&1; then stat_mode=bsd
  else return 1
  fi
  temp_base=${TMPDIR:-/tmp}
  temp_root=$(mktemp -d "$temp_base/mutation-check.XXXXXX" 2>/dev/null) || return 1
  case "$temp_root" in "$temp_base"/mutation-check.*) ;; *) return 1 ;; esac
  acquire_lock
  lock_status=$?
  case "$lock_status" in
    0) ;;
    2)
      preserve_lock=1
      echo "mutation-check: ERROR code=recovery-required recovery=.mutation-check.lock"
      return 1
      ;;
    *) return 1 ;;
  esac
  runtime_ready=1
}

cleanup() {
  cleanup_status=$?
  cleanup_error=0
  trap - EXIT HUP INT TERM
  terminate_active_test
  if ! restore_active; then
    preserve_lock=1
    cleanup_status=2
    cleanup_error=1
    echo "mutation-check: ERROR code=recovery-required recovery=.mutation-check.lock"
  fi
  if [ "$lock_owned" -eq 1 ] && [ "$preserve_lock" -eq 0 ]; then
    if journal_read owner && [ "$journal_value" = "$$" ]; then
      rm -rf "$lock_dir" >/dev/null 2>&1 || cleanup_error=1
    else
      cleanup_error=1
    fi
  fi
  if [ -n "$temp_root" ]; then
    rm -rf "$temp_root" >/dev/null 2>&1 || cleanup_error=1
  fi
  if [ "$cleanup_error" -ne 0 ]; then
    echo "mutation-check: ERROR code=cleanup" >&2
    cleanup_status=2
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT
trap 'terminate_active_test; exit 2' HUP INT TERM

mark_infra() {
  infra_total=$((infra_total + 1))
  echo "mutation-check: ERROR id=$1 code=$2"
}

run_test_command() {
  run_id=$1
  run_phase=$2
  run_case_id=$3
  shift 3
  test_log="$temp_root/$run_id.output"
  timeout_marker="$temp_root/$run_id.timeout"
  evidence_file="$temp_root/$run_id.evidence"
  status_file="$temp_root/$run_id.status"
  rm -f "$timeout_marker" >/dev/null 2>&1 || return 125
  rm -f "$evidence_file" >/dev/null 2>&1 || return 125
  rm -f "$status_file" >/dev/null 2>&1 || return 125
  evidence_marker="mutation-check-v1:$run_case_id"
  set -m
  MUTATION_CHECK_PHASE=$run_phase \
    MUTATION_CHECK_EVIDENCE_FILE=$evidence_file \
    MUTATION_CHECK_EVIDENCE_MARKER=$evidence_marker \
    MUTATION_CHECK_HARNESS_PID=$$ \
    bash -c '
      status_file=$1
      shift
      "$@"
      command_status=$?
      printf "%s\n" "$command_status" > "$status_file" || exit 125
      exit "$command_status"
    ' mutation-runner "$status_file" "$@" > "$test_log" 2>&1 &
  active_test_pgid=$!
  journal_write child_pgid "$active_test_pgid" || {
    set +m
    return 125
  }
  set +m
  run_started=$SECONDS
  while [ ! -f "$status_file" ]; do
    if [ $((SECONDS - run_started)) -ge "$timeout_seconds" ]; then
      : > "$timeout_marker" || true
      terminate_active_test
      rm -f "$lock_dir/child_pgid" >/dev/null 2>&1 || return 125
      return 124
    fi
    sleep 1
  done
  completed_pgid=$active_test_pgid
  wait "$completed_pgid" >/dev/null 2>&1 || true
  IFS= read -r test_status < "$status_file" || test_status=125
  case "$test_status" in ''|*[!0-9]*) test_status=125 ;; esac
  if kill -0 -- "-$active_test_pgid" >/dev/null 2>&1; then
    terminate_active_test
    rm -f "$lock_dir/child_pgid" >/dev/null 2>&1 || return 125
    return 125
  fi
  active_test_pgid=
  rm -f "$lock_dir/child_pgid" >/dev/null 2>&1 || return 125
  [ ! -f "$timeout_marker" ] || return 124
  return "$test_status"
}

create_mutated_copy() {
  mutation_source=$1
  mutation_output=$2
  mutation_from=$3
  mutation_to=$4
  case "$mutation_from$mutation_to" in *$'\n'*|*$'\r'*) return 42 ;; esac
  mutation_matches="$temp_root/matches-$case_total"
  LC_ALL=C grep -aFob -- "$mutation_from" "$mutation_source" \
    > "$mutation_matches" 2>/dev/null
  grep_status=$?
  [ "$grep_status" -le 1 ] || return 125
  match_count=$(wc -l < "$mutation_matches" 2>/dev/null | awk '{print $1}') \
    || return 125
  [ "$match_count" = 1 ] || return 42
  IFS=: read -r match_offset _ < "$mutation_matches" || return 125
  case "$match_offset" in ''|*[!0-9]*) return 125 ;; esac
  from_size=$(printf '%s' "$mutation_from" | wc -c | awk '{print $1}') \
    || return 125
  case "$from_size" in ''|*[!0-9]*) return 125 ;; esac
  cp -p "$mutation_source" "$mutation_output" >/dev/null 2>&1 || return 125
  : > "$mutation_output" || return 125
  if [ "$match_offset" -gt 0 ]; then
    dd if="$mutation_source" of="$mutation_output" bs=1 count="$match_offset" \
      >/dev/null 2>&1 || return 125
  fi
  printf '%s' "$mutation_to" >> "$mutation_output" || return 125
  remainder_offset=$((match_offset + from_size))
  dd if="$mutation_source" bs=1 skip="$remainder_offset" \
    >> "$mutation_output" 2>/dev/null || return 125
}

mutation_case() {
  if [ "$abort_run" -ne 0 ]; then return 0; fi
  if [ "$#" -lt 7 ]; then mark_infra invalid case-arguments; return 0; fi
  local case_id=$1 target=$2 original_fragment=$3 mutant_fragment=$4
  local expected_status=$5
  shift 5
  if [ "$1" != -- ]; then mark_infra invalid case-arguments; return 0; fi
  shift
  if [ "$#" -eq 0 ]; then mark_infra invalid case-command; return 0; fi
  local -a test_command=("$@")
  case_total=$((case_total + 1))
  if ! [[ "$case_id" =~ $label_regex ]]; then
    mark_infra invalid invalid-id
    return 0
  fi
  case "$expected_status" in ''|*[!0-9]*)
    mark_infra "$case_id" expected-status; return 0 ;;
  esac
  if [ "$expected_status" -lt 1 ] || [ "$expected_status" -gt 123 ]; then
    mark_infra "$case_id" expected-status
    return 0
  fi
  if [ -z "$original_fragment" ] || [ "$original_fragment" = "$mutant_fragment" ]; then
    mark_infra "$case_id" mutation-fragments
    return 0
  fi
  if ! init_runtime; then
    mark_infra "$case_id" runtime-init
    abort_run=1
    return 0
  fi
  if ! validate_relative_path "$target"; then
    mark_infra "$case_id" unsafe-target
    return 0
  fi
  target_path="$repo_root/$target"
  target_links=$(link_count "$target_path") || {
    mark_infra "$case_id" target-links
    return 0
  }
  [ "$target_links" = 1 ] || {
    mark_infra "$case_id" target-links
    return 0
  }
  target_size=$(wc -c < "$target_path" 2>/dev/null | awk '{print $1}') || {
    mark_infra "$case_id" target-read
    return 0
  }
  case "$target_size" in ''|*[!0-9]*)
    mark_infra "$case_id" target-size; return 0 ;;
  esac
  if [ "$target_size" -gt 4194304 ]; then
    mark_infra "$case_id" target-size
    return 0
  fi
  cp -p "$target_path" "$lock_dir/original" >/dev/null 2>&1 || {
    mark_infra "$case_id" backup-create
    return 0
  }
  active_original_hash=$(hash_file "$lock_dir/original") || {
    mark_infra "$case_id" backup-hash
    return 0
  }
  active_target=$target_path
  active_relative=$target
  active_mutated_hash=$active_original_hash
  if ! journal_write target "$target" \
    || ! journal_write original_hash "$active_original_hash" \
    || ! journal_write state prepared; then
    mark_infra "$case_id" journal-write
    abort_run=1
    return 0
  fi
  mutated_copy="$temp_root/case-$case_total.mutated"
  cp -p "$lock_dir/original" "$mutated_copy" >/dev/null 2>&1 || {
    restore_active || true
    mark_infra "$case_id" mutation-copy
    return 0
  }
  create_mutated_copy "$lock_dir/original" "$mutated_copy" \
    "$original_fragment" "$mutant_fragment"
  mutation_status=$?
  active_mutated_hash=$(hash_file "$mutated_copy") || mutation_status=125
  if [ "$mutation_status" -ne 0 ] \
    || [ "$active_mutated_hash" = "$active_original_hash" ]; then
    restore_active || { preserve_lock=1; abort_run=1; mark_infra "$case_id" restore-failed; return 0; }
    mark_infra "$case_id" mutation-cardinality
    return 0
  fi
  journal_write mutated_hash "$active_mutated_hash" || {
    preserve_lock=1; abort_run=1; mark_infra "$case_id" journal-write; return 0;
  }
  run_test_command "case-$case_total-baseline" baseline "$case_id" \
    "${test_command[@]}"
  baseline_status=$?
  baseline_evidence="$temp_root/case-$case_total-baseline.evidence"
  if [ -e "$baseline_evidence" ] || [ -L "$baseline_evidence" ]; then
    baseline_status=125
    baseline_evidence_present=1
  else
    baseline_evidence_present=0
  fi
  current_hash=$(hash_file "$active_target") || baseline_status=125
  if [ "$current_hash" != "$active_original_hash" ]; then
    journal_write state drift || true
    preserve_lock=1
    active_target=
    mark_infra "$case_id" baseline-mutated-target
    echo "mutation-check: ERROR code=recovery-required recovery=.mutation-check.lock"
    abort_run=1
    return 0
  fi
  if [ "$baseline_status" -ne 0 ]; then
    restore_active || { preserve_lock=1; abort_run=1; mark_infra "$case_id" restore-failed; return 0; }
    if [ "$baseline_evidence_present" -eq 1 ]; then
      mark_infra "$case_id" baseline-evidence
    else
      mark_infra "$case_id" baseline-red
    fi
    return 0
  fi
  validate_parent_path "$active_relative" || {
    restore_active || true
    mark_infra "$case_id" unsafe-target
    return 0
  }
  mv -f "$mutated_copy" "$active_target" >/dev/null 2>&1 || {
    restore_active || true
    mark_infra "$case_id" mutation-write
    return 0
  }
  journal_write state mutated || {
    preserve_lock=1; abort_run=1; mark_infra "$case_id" journal-write; return 0;
  }
  run_test_command "case-$case_total-mutant" mutant "$case_id" \
    "${test_command[@]}"
  mutant_status=$?
  mutant_evidence="$temp_root/case-$case_total-mutant.evidence"
  expected_evidence="$temp_root/case-$case_total-mutant.expected"
  printf '%s\n' "mutation-check-v1:$case_id" > "$expected_evidence" \
    || mutant_status=125
  evidence_valid=0
  if [ -f "$mutant_evidence" ] && [ ! -L "$mutant_evidence" ]; then
    evidence_links=$(link_count "$mutant_evidence") || evidence_links=0
    if [ "$evidence_links" = 1 ] \
      && cmp -s "$expected_evidence" "$mutant_evidence" 2>/dev/null; then
      evidence_valid=1
    fi
  fi
  current_hash=$(hash_file "$active_target") || mutant_status=125
  if [ "$current_hash" != "$active_mutated_hash" ]; then
    journal_write state drift || true
    preserve_lock=1
    active_target=
    mark_infra "$case_id" test-mutated-target
    echo "mutation-check: ERROR code=recovery-required recovery=.mutation-check.lock"
    abort_run=1
    return 0
  fi
  if ! restore_active; then
    preserve_lock=1
    abort_run=1
    mark_infra "$case_id" restore-failed
    return 0
  fi
  if [ "$mutant_status" -eq 0 ]; then
    survived_total=$((survived_total + 1))
    echo "mutation-check: FAIL id=$case_id code=mutant-survived"
  elif [ "$mutant_status" -eq "$expected_status" ]; then
    if [ "$evidence_valid" -eq 1 ]; then
      killed_total=$((killed_total + 1))
      echo "mutation-check: PASS id=$case_id"
    else
      mark_infra "$case_id" mutant-evidence
    fi
  else
    mark_infra "$case_id" mutant-outcome
  fi
}

# Project-owned executable declarations. Keep this file to quoted
# mutation_case calls only; command output and shell diagnostics stay private.
# shellcheck source=/dev/null
source "$cases_file" 2>/dev/null
cases_status=$?
if [ "$cases_status" -ne 0 ]; then
  echo "mutation-check: ERROR code=cases-source" >&2
  exit 2
fi
if [ "$case_total" -eq 0 ] \
  && { [ -e "$lock_dir" ] || [ -L "$lock_dir" ]; }; then
  if ! init_runtime; then
    echo "mutation-check: ERROR code=runtime-init" >&2
    exit 2
  fi
fi
if [ "$infra_total" -gt 0 ]; then
  echo "mutation-check: ERROR cases=$case_total killed=$killed_total survived=$survived_total infra=$infra_total" >&2
  exit 2
fi
if [ "$survived_total" -gt 0 ]; then
  echo "mutation-check: FAIL cases=$case_total killed=$killed_total survived=$survived_total"
  exit 1
fi
if [ "$case_total" -eq 0 ]; then
  echo "mutation-check: SKIP cases=0 configured=0"
  exit 0
fi
echo "mutation-check: PASS cases=$case_total killed=$killed_total"
