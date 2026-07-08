#!/usr/bin/env bash
#
# Local pre-PR review helper for {{ project_name }}.
#
# Prints the current branch's diff vs a base ref, prefixed with a reviewer
# prompt. Pipe the output into a review chat (Claude, Codex, etc.) for a fast
# self-review BEFORE opening the PR — complements the server-side
# .github/workflows/ai-pr-review.yml.
#
# Usage:
#   bash scripts/ai-review.sh                  # base: origin/master
#   bash scripts/ai-review.sh origin/develop   # custom base
#   bash scripts/ai-review.sh | pbcopy         # straight to clipboard (macOS)
#
set -euo pipefail

BASE="${1:-origin/master}"

git fetch -q origin >/dev/null 2>&1 || true

cat <<PROMPT
You are reviewing a pull request for {{ project_name }}.
{{ project_tagline }}

Review the diff below for, in priority order:
  1. Correctness — wrong logic, bad state transitions, data loss
  2. Security — auth bypass, injection, unintended data exposure
  3. Migration safety — non-idempotent or edited applied migrations
  4. Breaking changes — API/schema changes that break clients
  5. Project invariants — see ARCHITECTURE.md

End with exactly one of: BLOCKING, NON-BLOCKING, or LGTM.

--- DIFF (vs ${BASE}) ---
PROMPT

git --no-pager diff "${BASE}...HEAD"
