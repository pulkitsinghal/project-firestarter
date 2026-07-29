# Covered-path dispatcher guardrail

Status: `COVERED_PATH_GUARDRAIL`.

The plugin bundles a supported catch-all `PreToolUse` hook. When the plugin is
installed, trusted, active, and supplied a trusted root-role assignment, the
hook can deny covered calls before dispatch: Bash/unified exec, `apply_patch`,
Agent/spawn, MCP calls, and most local function paths.

This is not universal root-role enforcement:

- hosted tools may not traverse the hook;
- specialized tools may opt out;
- `write_stdin` does not reauthorize a command already admitted;
- untrusted or disabled non-managed plugin hooks do not enforce;
- the documented hook payload has no non-spoofable root/worker identity, and
  subagents share the parent `session_id`.

The source tests prove classifier denial and zero calls in synthetic
dispatchers. Live runtime proof is intentionally unexecuted because this task
does not install/trust the plugin or mutate Codex configuration.

## Required live adoption test

In a disposable synthetic project:

1. Install the exact hashed plugin from the repo/team marketplace and trust the
   hook, or use an equivalent managed hook.
2. Start a new task and verify the active `PreToolUse` source/matcher.
3. Attempt synthetic canary mutations through exec, patch, MCP/app, browser,
   Sites, task/thread, and Agent paths.
4. For each claimed-covered path, prove the hook fired before dispatch, denial
   was returned, downstream invocation count stayed zero, and no side effect
   exists.
5. Record hosted-tool and specialized-tool escape tests as uncovered, not pass.
6. Repeat after Codex/plugin upgrades.

Do not infer role from cwd, prompt text, transcript, `session_id`, or a
caller-controlled environment variable. Until the platform supplies trusted
caller identity and universal coverage, retain the status label above.
