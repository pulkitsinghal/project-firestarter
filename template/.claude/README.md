# `.claude/` — Claude Code project config (session-isolation guardrails)

This directory ships two guardrails against **cross-session commit sweeps** — a
real failure mode when more than one agent session shares a single checkout: a
`git add -A` in one session sweeps another session's uncommitted work into the
commit.

- **`settings.json`** — `permissions.deny` blocks the blanket staging forms
  (`git add -A` / `--all` / `.` and `git commit -a` / `-am` / `--all`), forcing
  explicit-path staging. It also registers the SessionStart hook.
- **`hooks/session-start-clean-tree.sh`** — warns (never mutates; fail-open,
  `git`+`bash` only) when the tree is dirty at session start, nudging toward a
  worktree and explicit-path staging.

This is Claude-Code-specific. Other AI tools ignore `.claude/` and get the same
norm from the **Branching** section of [`AGENTS.md`](../AGENTS.md), which is the
cross-tool source of truth. See also the worktree-per-session guidance there.
