#!/usr/bin/env bash
# SessionStart guard — multi-session safety.
#
# Warns (does NOT mutate) when the working tree is dirty at session start, so a
# new session isolates its work in a git worktree instead of branching in place
# and sweeping another session's uncommitted changes into a commit.
#
# Warn-only by design: auto-stashing a concurrent session's live edits would
# itself be a form of sweeping. An opt-in auto-stash block is at the bottom.
#
# Requires only `git` + `bash` (no node/jq — this project runs its toolchains in
# Docker, nothing on the host). Fail-open: any error just means no warning; it
# never blocks the session.

set -uo pipefail

dirty="$(git status --porcelain 2>/dev/null || true)"

if [ -n "$dirty" ]; then
  echo "⚠️  Working tree is NOT clean at session start:"
  echo "$dirty" | sed 's/^/    /'
  echo ""
  echo "Another session may have uncommitted work in this checkout. Before any git work:"
  echo "  • Do NOT 'git add -A' / 'git add .' — stage explicit paths only"
  echo "    (the deny rules in .claude/settings.json block the blanket forms)."
  echo "  • For NEW work, isolate in a worktree instead of branching in place:"
  echo "      git worktree add ../{{ project_slug }}-wt-<task> -b <type>/<scope>-<slug> master"
  echo "  • Only commit files THIS session created or edited; leave the rest."
  echo "  • Verify 'git status' shows only your files before committing."
fi

# ── Opt-in: auto-stash instead of warn ────────────────────────────────────────
# DANGER: only enable if this checkout is never used by two live sessions at
# once — stashing a concurrent session's edits out from under it loses their
# in-progress state from the tree. To enable, uncomment:
#
# if [ -n "$dirty" ]; then
#   git stash push --include-untracked -m "session-start-autostash $(git rev-parse --short HEAD)" >/dev/null 2>&1 || true
#   echo "Stashed pre-existing changes. Restore with: git stash list / git stash pop"
# fi

exit 0
