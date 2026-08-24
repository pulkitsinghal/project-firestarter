#!/usr/bin/env bash
# Persist a sanitized deferred-work record before projecting a content-free issue.

set +x
set -uo pipefail
export LC_ALL=C
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=
export GH_PROMPT_DISABLED=1
export GH_PAGER=cat
export NO_COLOR=1
umask 077

usage() {
  echo "usage: scripts/defer-work.sh <dw-opaque-hex-id> [--local-only] < record.md" >&2
}

fail() {
  echo "defer-work: ERROR code=$1" >&2
  exit 2
}

warn_tracker() {
  echo "defer-work: WARN code=$1 tracker=best-effort canonical=docs/DEFERRED_WORK.md" >&2
}

valid_id() {
  candidate_id=$1
  case "$candidate_id" in dw-*) candidate_hex=${candidate_id#dw-} ;; *) return 1 ;; esac
  case "$candidate_hex" in ""|*[!0-9a-f]*) return 1 ;; esac
  [ "${#candidate_hex}" -ge 16 ] && [ "${#candidate_hex}" -le 64 ]
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  usage
  exit 2
fi

record_id=$1
valid_id "$record_id" || fail "unsafe-id"
tracking=enabled
if [ "$#" -eq 2 ]; then
  case "$2" in
    --local-only) tracking=disabled ;;
    *) usage; exit 2 ;;
  esac
fi

for required_tool in git grep awk wc od mktemp mkdir rmdir rm cp cat mv dd stat sleep kill; do
  command -v "$required_tool" >/dev/null 2>&1 || fail "missing-tool"
done

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || fail "not-a-git-repository"
is_bare=$(git rev-parse --is-bare-repository 2>/dev/null) || fail "repository-state"
[ "$is_bare" = false ] || fail "bare-repository"
repo_root=$(cd "$repo_root" 2>/dev/null && pwd -P) || fail "unreadable-repository"
cd "$repo_root" 2>/dev/null || fail "unreadable-repository"

ledger=docs/DEFERRED_WORK.md

ledger_link_count() {
  stat -c %h "$ledger" 2>/dev/null || stat -f %l "$ledger" 2>/dev/null
}

validate_ledger_path() {
  [ -d docs ] && [ ! -L docs ] || return 1
  [ -f "$ledger" ] && [ ! -L "$ledger" ] || return 1
  git ls-files --error-unmatch -- "$ledger" >/dev/null 2>&1 || return 1
  link_count=$(ledger_link_count) || return 1
  [ "$link_count" = 1 ] || return 1
}

validate_record_schema() {
  awk '
    /^Summary:/ {
      summary += 1
      if ($0 !~ /^Summary:[[:space:]]*[^[:space:]]/) invalid = 1
    }
    /^Status:/ {
      status += 1
      if ($0 !~ /^Status:[[:space:]]*(deferred|blocked)[[:space:]]*$/) invalid = 1
    }
    /^Dependency:/ {
      dependency += 1
      if ($0 !~ /^Dependency:[[:space:]]*[^[:space:]]/) invalid = 1
    }
    /^Completion test:/ {
      completion += 1
      if ($0 !~ /^Completion test:[[:space:]]*[^[:space:]]/) invalid = 1
    }
    END {
      if (invalid || summary != 1 || status != 1 || dependency != 1 || completion != 1) exit 1
    }
  ' "$1" >/dev/null 2>&1
}

hash_file() {
  hash_target=$1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$hash_target" 2>/dev/null | awk '{print $1}'
    return ${PIPESTATUS[0]}
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$hash_target" 2>/dev/null | awk '{print $1}'
    return ${PIPESTATUS[0]}
  fi
  return 1
}

valid_hash() {
  candidate_hash=$1
  case "$candidate_hash" in ""|*[!0-9a-f]*) return 1 ;; esac
  [ "${#candidate_hash}" -eq 64 ]
}

validate_ledger_path || fail "canonical-ledger"

private_prefix=$(git rev-parse --git-path defer-work-private 2>/dev/null) || fail "repository-state"
[ -n "$private_prefix" ] || fail "repository-state"
private_dir=$(mktemp -d "${private_prefix}.XXXXXX" 2>/dev/null) || fail "private-temp-create"
case "$private_dir" in "${private_prefix}."*) ;; *) fail "private-temp-path" ;; esac

raw_record=$private_dir/raw
canonical_record=$private_dir/canonical
validation_record=$private_dir/validation
seen_ids=$private_dir/seen
gh_output=$private_dir/gh-output
gh_status=$private_dir/gh-status
temp_file=
lock_path=
lock_owned=0

cleanup() {
  cleanup_status=$?
  trap - EXIT HUP INT TERM
  if [ -n "${temp_file:-}" ] && [ -f "$temp_file" ]; then
    rm -f -- "$temp_file" >/dev/null 2>&1 || cleanup_status=2
  fi
  for private_file in "$raw_record" "$canonical_record" "$validation_record" "$seen_ids" "$gh_output" "$gh_status"; do
    [ ! -e "$private_file" ] || rm -f -- "$private_file" >/dev/null 2>&1 || cleanup_status=2
  done
  [ ! -d "$private_dir" ] || rmdir -- "$private_dir" >/dev/null 2>&1 || cleanup_status=2
  if [ "${lock_owned:-0}" -eq 1 ]; then
    rmdir -- "$lock_path" >/dev/null 2>&1 || cleanup_status=2
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 2' HUP INT TERM

# Read at most one byte beyond the limit so unbounded input is rejected without
# materializing it. The canonical copy normalizes CRLF and adds one final LF.
dd bs=1 count=65537 of="$raw_record" 2>/dev/null || fail "record-read"
raw_size=$(wc -c < "$raw_record" 2>/dev/null | awk '{print $1}') || fail "record-read"
case "$raw_size" in ""|*[!0-9]*) fail "record-read" ;; esac
[ "$raw_size" -gt 0 ] && [ "$raw_size" -le 65536 ] || fail "record-size"

# Permit tab, LF, CRLF, printable ASCII, and UTF-8 bytes. Reject NUL and other
# control bytes before any line-oriented parsing.
od -An -v -tu1 "$raw_record" 2>/dev/null | awk '
  {
    for (i = 1; i <= NF; i += 1) {
      byte = $i + 0
      if ((byte < 32 && byte != 9 && byte != 10 && byte != 13) || byte == 127) exit 1
    }
  }
' >/dev/null 2>&1 || fail "record-control-byte"

awk '{ sub(/\r$/, ""); print }' "$raw_record" > "$canonical_record" || fail "record-normalize"
od -An -v -tu1 "$canonical_record" 2>/dev/null | awk '
  {
    for (i = 1; i <= NF; i += 1) if ($i + 0 == 13) exit 1
  }
' >/dev/null 2>&1 || fail "record-control-byte"

canonical_size=$(wc -c < "$canonical_record" 2>/dev/null | awk '{print $1}') || fail "record-read"
case "$canonical_size" in ""|*[!0-9]*) fail "record-read" ;; esac
[ "$canonical_size" -gt 0 ] && [ "$canonical_size" -le 65536 ] || fail "record-size"

grep -F '<!-- deferred-work:' "$canonical_record" >/dev/null 2>&1
marker_status=$?
[ "$marker_status" -eq 1 ] || {
  [ "$marker_status" -eq 0 ] && fail "record-marker"
  fail "record-read"
}
validate_record_schema "$canonical_record" || fail "record-schema"
record_hash=$(hash_file "$canonical_record") || fail "sha256-unavailable"
valid_hash "$record_hash" || fail "sha256-unavailable"

lock_path=$(git rev-parse --git-path defer-work.lock 2>/dev/null) || fail "repository-state"
[ -n "$lock_path" ] || fail "repository-state"
mkdir -- "$lock_path" >/dev/null 2>&1 || fail "recovery-required"
lock_owned=1

# Recheck after acquiring the lock; the lock serializes cooperating writers in
# this working tree but cannot defeat a hostile same-user filesystem process.
validate_ledger_path || fail "canonical-ledger"

validate_whole_ledger() {
  : > "$seen_ids" || return 1
  : > "$validation_record" || return 1
  parser_state=outside
  current_id=
  current_hash=

  while IFS= read -r ledger_line || [ -n "$ledger_line" ]; do
    if [ "$parser_state" = outside ]; then
      case "$ledger_line" in
        '<!-- deferred-work:v1 id='*' sha256='*' -->')
          marker_body=${ledger_line#'<!-- deferred-work:v1 id='}
          marker_id=${marker_body%% *}
          marker_tail=${marker_body#"$marker_id sha256="}
          marker_hash=${marker_tail%' -->'}
          [ "$ledger_line" = "<!-- deferred-work:v1 id=$marker_id sha256=$marker_hash -->" ] || return 1
          valid_id "$marker_id" || return 1
          valid_hash "$marker_hash" || return 1
          ! grep -Fqx "$marker_id" "$seen_ids" 2>/dev/null || return 1
          printf '%s\n' "$marker_id" >> "$seen_ids" || return 1
          : > "$validation_record" || return 1
          current_id=$marker_id
          current_hash=$marker_hash
          parser_state=inside
          ;;
        *'<!-- deferred-work:'*) return 1 ;;
      esac
    else
      if [ "$ledger_line" = "<!-- deferred-work:v1 end id=$current_id -->" ]; then
        validate_record_schema "$validation_record" || return 1
        observed_hash=$(hash_file "$validation_record") || return 1
        [ "$observed_hash" = "$current_hash" ] || return 1
        parser_state=outside
        current_id=
        current_hash=
      else
        case "$ledger_line" in *'<!-- deferred-work:'*) return 1 ;; esac
        printf '%s\n' "$ledger_line" >> "$validation_record" || return 1
      fi
    fi
  done < "$ledger"

  [ "$parser_state" = outside ]
}

validate_whole_ledger || fail "ledger-corrupt"

start_marker="<!-- deferred-work:v1 id=$record_id sha256=$record_hash -->"
end_marker="<!-- deferred-work:v1 end id=$record_id -->"
if grep -Fqx "$record_id" "$seen_ids" 2>/dev/null; then
  grep -Fqx "$start_marker" "$ledger" 2>/dev/null || fail "record-id-conflict"
  local_result=replayed
else
  ledger_dir=${ledger%/*}
  temp_file=$(mktemp "$ledger_dir/.deferred-work.XXXXXX" 2>/dev/null) || fail "temporary-file"
  case "$temp_file" in "$ledger_dir"/.deferred-work.*) ;; *) fail "temporary-file" ;; esac
  cp -p -- "$ledger" "$temp_file" >/dev/null 2>&1 || fail "canonical-copy"
  {
    printf '\n%s\n' "$start_marker"
    cat -- "$canonical_record"
    printf '%s\n' "$end_marker"
  } >> "$temp_file" || fail "canonical-write"
  mv -- "$temp_file" "$ledger" >/dev/null 2>&1 || fail "canonical-replace"
  temp_file=
  local_result=created
fi

# The local transition is complete before any network/auth command can run.
rmdir -- "$lock_path" >/dev/null 2>&1 || fail "lock-release"
lock_owned=0

if [ "$tracking" = disabled ]; then
  echo "defer-work: RECORDED id=$record_id local=$local_result tracker=disabled"
  exit 0
fi

run_gh_bounded() {
  rm -f -- "$gh_output" "$gh_status" >/dev/null 2>&1 || return 2

  # Bash 3.2 has no wait-with-timeout. The wrapper makes gh a process-group
  # leader; its TERM trap kills that group, reaps gh, and then exits. A private
  # status file lets the parent distinguish completion from timeout.
  (
    set -m
    gh "$@" > "$gh_output" 2>/dev/null &
    bounded_child=$!
    set +m
    bounded_timeout_cleanup() {
      trap - TERM
      kill -TERM -- "-$bounded_child" >/dev/null 2>&1 || true
      sleep 1
      kill -KILL -- "-$bounded_child" >/dev/null 2>&1 || true
      wait "$bounded_child" >/dev/null 2>&1 || true
      exit 124
    }
    trap bounded_timeout_cleanup TERM
    wait "$bounded_child"
    bounded_status=$?
    trap - TERM
    printf '%s\n' "$bounded_status" > "$gh_status"
  ) &
  bounded_wrapper=$!

  bounded_ticks=0
  while [ ! -s "$gh_status" ] && [ "$bounded_ticks" -lt 100 ]; do
    sleep 0.1
    bounded_ticks=$((bounded_ticks + 1))
  done

  if [ -s "$gh_status" ]; then
    wait "$bounded_wrapper" >/dev/null 2>&1 || true
    IFS= read -r bounded_status < "$gh_status" || return 2
    case "$bounded_status" in ""|*[!0-9]*) return 2 ;; esac
    return "$bounded_status"
  fi

  kill -TERM "$bounded_wrapper" >/dev/null 2>&1 || true
  wait "$bounded_wrapper" >/dev/null 2>&1 || true
  : > "$gh_output" || return 2
  return 124
}

if ! command -v gh >/dev/null 2>&1; then
  warn_tracker "tracker-unavailable"
  echo "defer-work: RECORDED id=$record_id local=$local_result tracker=pending"
  exit 0
fi

if ! run_gh_bounded auth status --hostname github.com; then
  warn_tracker "tracker-auth"
  echo "defer-work: RECORDED id=$record_id local=$local_result tracker=pending"
  exit 0
fi

origin_url=$(git remote get-url origin 2>/dev/null) || origin_url=
github_scp_prefix='git''@github.com:'
github_ssh_prefix='ssh://git''@github.com/'
case "$origin_url" in
  https://github.com/*) repo_slug=${origin_url#https://github.com/} ;;
  "$github_scp_prefix"*) repo_slug=${origin_url#"$github_scp_prefix"} ;;
  "$github_ssh_prefix"*) repo_slug=${origin_url#"$github_ssh_prefix"} ;;
  *) repo_slug= ;;
esac
repo_slug=${repo_slug%.git}
repo_slug=${repo_slug%/}
if [[ ! "$repo_slug" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  warn_tracker "tracker-origin"
  echo "defer-work: RECORDED id=$record_id local=$local_result tracker=pending"
  exit 0
fi

issue_title="Deferred work record: $record_id"
tracker_marker="<!-- deferred-work-tracker:v1 id=$record_id -->"
issue_body="This issue is a visibility projection only; the tracked file is authoritative.

Canonical record: docs/DEFERRED_WORK.md
Record ID: $record_id

Do not copy deferred-record content, credentials, private data, or competitive details into this issue.

$tracker_marker"

# GitHub has no atomic issue upsert. Exact-marker search minimizes duplicate
# creation, but a create-response loss can still require manual reconciliation.
if ! run_gh_bounded issue list \
  --repo "$repo_slug" \
  --state all \
  --search "$issue_title in:title" \
  --limit 20 \
  --json number,title,body,state \
  --jq ".[] | select(.title == \"$issue_title\" and ((.body // \"\") | contains(\"$tracker_marker\"))) | [.number, .state] | @tsv"; then
  warn_tracker "tracker-search"
  echo "defer-work: RECORDED id=$record_id local=$local_result tracker=pending"
  exit 0
fi
existing_match=$(cat -- "$gh_output" 2>/dev/null) || existing_match=

case "$existing_match" in
  "")
    if run_gh_bounded issue create --repo "$repo_slug" --title "$issue_title" --body "$issue_body"; then
      tracker_result=created
    else
      warn_tracker "tracker-write"
      tracker_result=pending
    fi
    ;;
  *$'\n'*)
    warn_tracker "tracker-ambiguous"
    tracker_result=pending
    ;;
  *)
    tab=$'\t'
    existing_number=${existing_match%%"$tab"*}
    existing_state=${existing_match#*"$tab"}
    case "$existing_number" in
      ""|*[!0-9]*) existing_state=INVALID ;;
    esac
    case "$existing_state" in
      OPEN)
        tracker_result=present
        ;;
      CLOSED)
        if run_gh_bounded issue reopen "$existing_number" --repo "$repo_slug"; then
          tracker_result=reopened
        else
          warn_tracker "tracker-write"
          tracker_result=pending
        fi
        ;;
      *)
        warn_tracker "tracker-ambiguous"
        tracker_result=pending
        ;;
    esac
    ;;
esac

echo "defer-work: RECORDED id=$record_id local=$local_result tracker=$tracker_result"
exit 0
