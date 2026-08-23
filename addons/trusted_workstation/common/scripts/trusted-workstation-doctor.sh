#!/usr/bin/env bash
# Read-only preflight. It never invokes op, tailscale, git-crypt, or mutagen.
set -u
export LC_ALL=C

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
REPOSITORY_FILE="$SCRIPT_DIR/../trusted-workstation/repository.txt"
if [ ! -f "$REPOSITORY_FILE" ]; then printf 'BLOCKED repository configuration is missing\n' >&2; exit 2; fi
load_repository() {
  repository_bytes=$(wc -c < "$REPOSITORY_FILE" | tr -d ' ')
  repository_lines=$(awk 'END { print NR + 0 }' "$REPOSITORY_FILE")
  [ "$repository_bytes" -le 142 ] && [ "$repository_lines" -eq 1 ] || return 1
  repository_lf=0
  if IFS= read -r EXPECTED_REPO < "$REPOSITORY_FILE"; then repository_lf=1; fi
  repository_cr=0; carriage_return=$(printf '\r')
  if [ "$repository_lf" -eq 1 ]; then
    case "$EXPECTED_REPO" in *"$carriage_return") EXPECTED_REPO=${EXPECTED_REPO%"$carriage_return"}; repository_cr=1;; esac
  fi
  [ "$repository_bytes" -eq $((${#EXPECTED_REPO} + repository_lf + repository_cr)) ] || return 1
}
if ! load_repository; then printf 'BLOCKED repository configuration is invalid\n' >&2; exit 2; fi
case "$EXPECTED_REPO" in
  ?*/*) ;;
  *) printf 'BLOCKED repository configuration is invalid\n' >&2; exit 2 ;;
esac
if printf '%s' "$EXPECTED_REPO" | grep -qvE '^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100}$'; then
  printf 'BLOCKED repository configuration is invalid\n' >&2; exit 2
fi
case "${EXPECTED_REPO#*/}" in .|..) printf 'BLOCKED repository configuration is invalid\n' >&2; exit 2;; esac
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

validate_remote_urls() {
  kind=$1
  if [ "$kind" = fetch ]; then
    urls="$(git remote get-url --all origin 2>/dev/null)" || return 1
  else
    urls="$(git remote get-url --push --all origin 2>/dev/null)" || return 1
  fi
  [ -n "$urls" ] && [ "${#urls}" -le 8192 ] || return 1
  saved_ifs=$IFS
  github_scp_prefix='git''@github.com:'
  IFS='
'
  for remote in $urls; do
    [ -n "$remote" ] && [ "${#remote}" -le 2048 ] || { IFS=$saved_ifs; return 1; }
    case "$remote" in
      https://github.com/*) normalized=${remote%.git} ;;
      "$github_scp_prefix"*) normalized=${remote#"$github_scp_prefix"}; normalized="https://github.com/$normalized"; normalized=${normalized%.git} ;;
      *) IFS=$saved_ifs; return 1 ;;
    esac
    [ "$normalized" = "https://github.com/$EXPECTED_REPO" ] || { IFS=$saved_ifs; return 1; }
  done
  IFS=$saved_ifs
}
if validate_remote_urls fetch && validate_remote_urls push; then
  report PASS 'origin fetch and push URLs match the configured repository'
else
  report BLOCKED 'origin fetch or push URL does not match the configured repository'; fail=1
fi

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
