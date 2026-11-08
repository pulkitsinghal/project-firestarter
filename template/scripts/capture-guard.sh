#!/usr/bin/env bash
# Pre-capture workstation-hygiene precondition: fail closed BEFORE any host-side
# screenshot / computer-use capture when a project-declared sensitive process is
# running, or when the workstation cannot be enumerated at all.
#
# FEATURE_HANDOFF.md section 5 is the RULE ("never put ... unrelated workstation
# content in screenshots"); this is its executable precondition. Enforce it
# before the capture, not as a review afterwards -- the moment of capture is the
# one time the rule will not be remembered. Prefer window-targeted captures so
# bystander content is excluded structurally rather than by closing things first.
#
# Privacy: emits fixed rule codes and counts only -- never a process name, window
# title, pid, or path (the diagnostics discipline repo-hygiene.sh and
# gate-selftest.sh already hold to). pgrep's output is discarded; only its exit
# status is read.
#
# Patterns come from the project-owned scripts/capture-guard-patterns.sh beside
# this script (never a caller-substitutable path), seeded empty. No patterns ->
# truthful SKIP, not a pass (the mutation-check.sh precedent), so a fresh stamp
# stays green and the guard never claims it checked a workstation it did not.
#
# The containerized storyboard harness (make storyboard) is out of scope: it is
# headless, in-container, and app-only, so there is no bystander surface.
#
# Exit codes:
#   0  SKIP (no patterns declared) or PASS (enumerated; nothing sensitive running)
#   1  BLOCK: a declared sensitive process is running -- do not capture
#   2  BLOCK: cannot enumerate (no enumerator / it errored / bad declaration)

set -uo pipefail
export LC_ALL=C
prog=capture-guard

# Deliberate guard messages go to a stable copy of stderr (fd 3). The patterns
# file is sourced under `2>/dev/null` so bash's own parse-error noise -- which
# could echo a line of the declaration -- is suppressed; fd 3 keeps our fixed
# rule codes (emitted even from inside that sourced context) visible.
exec 3>&2

script_dir=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || {
  echo "${prog}: BLOCK code=self-locate-failed (do not capture)" >&3
  exit 2
}
patterns_file="$script_dir/capture-guard-patterns.sh"

patterns_count=0
matched_count=0
enum_failed=0
enumerator_ok=0
command -v pgrep >/dev/null 2>&1 && enumerator_ok=1

# capture_pattern <process-name pattern>  (called by capture-guard-patterns.sh).
# An extended regex matched against the process NAME by pgrep. The pattern is
# never echoed; a blank, whitespace-only, or flag-shaped declaration fails closed.
capture_pattern() {
  _pattern=${1:-}
  case "$_pattern" in
    -*) echo "${prog}: BLOCK code=unsafe-pattern (do not capture)" >&3; exit 2 ;;
  esac
  # A declaration with no non-whitespace character is blank in substance: counting
  # it and handing " " to pgrep would report a hollow PASS for a pattern that
  # matches nothing the author meant.
  case "$_pattern" in
    *[![:space:]]*) : ;;
    *) echo "${prog}: BLOCK code=empty-pattern (do not capture)" >&3; exit 2 ;;
  esac
  patterns_count=$((patterns_count + 1))
  if [ "$enumerator_ok" -ne 1 ]; then
    enum_failed=1
    return 0
  fi
  pgrep "$_pattern" >/dev/null 2>&1
  _rc=$?
  if [ "$_rc" -eq 0 ]; then
    matched_count=$((matched_count + 1))
  elif [ "$_rc" -ne 1 ]; then
    enum_failed=1
  fi
}

[ -f "$patterns_file" ] || {
  echo "${prog}: BLOCK code=patterns-file-missing (do not capture)" >&3
  exit 2
}
# shellcheck source=/dev/null
# stdout is suppressed too: a project-owned declaration should only call
# capture_pattern (which reports via fd 3), never write to stdout; squelching
# both keeps the guard's output to its own fixed codes and counts.
. "$patterns_file" >/dev/null 2>&1 || {
  echo "${prog}: BLOCK code=patterns-source-failed (do not capture)" >&3
  exit 2
}

if [ "$patterns_count" -eq 0 ]; then
  echo "${prog}: SKIP patterns=0 (no sensitive-process patterns declared)"
  exit 0
fi
# Positive control: before trusting any "no match", confirm the enumerator can
# match a universally-present process. A pgrep that exists but silently reports
# "no match" for everything would otherwise turn a running sensitive process into
# a hollow PASS -- the one enumeration failure the present/erroring checks above
# cannot see. "." matches any process name, so on a live host it always matches;
# an enumerator that cannot even match "." is broken, and its no-match is a lie.
if [ "$enum_failed" -eq 0 ] && [ "$enumerator_ok" -eq 1 ]; then
  pgrep '.' >/dev/null 2>&1 || enum_failed=1
fi
if [ "$enum_failed" -ne 0 ]; then
  echo "${prog}: BLOCK code=enumeration-unavailable patterns=${patterns_count} (do not capture)" >&3
  exit 2
fi
if [ "$matched_count" -gt 0 ]; then
  echo "${prog}: BLOCK matched_patterns=${matched_count} patterns=${patterns_count} (hide them or use a window-targeted capture)" >&3
  exit 1
fi
echo "${prog}: PASS patterns=${patterns_count} matched=0"
exit 0
