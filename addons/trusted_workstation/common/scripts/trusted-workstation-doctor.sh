#!/usr/bin/env bash
# Read-only preflight. It never invokes op, tailscale, git-crypt, or mutagen.
set -u

EXPECTED_REPO='{{ trusted_workstation_repo }}'
fail=0
report() { printf '%-12s %s\n' "$1" "$2"; }
has_command() { command -v "$1" >/dev/null 2>&1; }

if [ -z "${BASH_VERSION:-}" ] || [ "${BASH_VERSINFO[0]:-0}" -lt 3 ]; then
  report BLOCKED 'Bash 3.2 or newer is required'; exit 2
fi
if ! has_command git; then report BLOCKED 'git is not available'; exit 1; fi
root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$root" ]; then report BLOCKED 'run this command inside the repository clone'; exit 1; fi

git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null || true)"
common_dir="$(git rev-parse --git-common-dir 2>/dev/null || true)"
case "$common_dir" in /*) ;; *) common_dir="$root/$common_dir" ;; esac
canonical_root="$(CDPATH= cd -- "$root" 2>/dev/null && pwd -P || true)"
canonical_git="$(CDPATH= cd -- "$git_dir" 2>/dev/null && pwd -P || true)"
physical_pwd="$(pwd -P 2>/dev/null || true)"
cursor=$root; linked=0
while [ -n "$cursor" ] && [ "$cursor" != "/" ]; do
  if [ -L "$cursor" ]; then linked=1; break; fi
  cursor=${cursor%/*}; [ -n "$cursor" ] || cursor=/
done
if [ "$linked" -eq 0 ] && [ "$PWD" = "$physical_pwd" ] && [ -d "$root/.git" ] && [ ! -L "$root/.git" ] &&
   [ "$canonical_root/.git" = "$canonical_git" ] && [ "$common_dir" = "$git_dir" ]; then
  report PASS 'independent clone metadata is canonical and clone-owned'
else report BLOCKED 'clone root or Git metadata is linked, external, or shared'; fail=1; fi

remote="$(git remote get-url origin 2>/dev/null || true)"
normalized="$(printf '%s' "$remote" | sed -E 's#^git@github.com:#https://github.com/#; s#\.git$##')"
case "$normalized" in
  "https://github.com/$EXPECTED_REPO") report PASS 'origin matches the configured repository' ;;
  *) report BLOCKED 'origin does not match the configured repository'; fail=1 ;;
esac

for tool in git-crypt op tailscale; do
  if has_command "$tool"; then report PASS "$tool is available (not invoked)"
  else report BLOCKED "$tool is not available"; fail=1; fi
done
if has_command mutagen; then report OPTIONAL 'mutagen is available (not invoked)'
else report OPTIONAL 'mutagen is absent; synchronization stays disabled'; fi

hooks="$(git config --local --get core.hooksPath 2>/dev/null || true)"
if [ "$hooks" = '.githooks' ]; then report PASS 'repository-local hooks path is active'
else report INFO 'repository-local hooks are not installed; phase 1 will not install them'; fi
exit "$fail"
