# PM Proxy Orchestrator

Version `0.3.0` is a source-only Codex plugin for Firestarter control-plane
interface `1.0`. It makes task reservation, policy receipts, approval routing,
fenced handback, successor creation, and queue recycling operational without
installing anything globally.

The plugin does not bundle or replace Firestarter's SQLite authority. Configure
an absolute path to the compatible `orchestrator_control.py` and an initialized
private state directory at use time. See `docs/OPERATIONS.md` and
`docs/INSTALL_UPDATE_ROLLBACK.md`.

Schema `1.2` adds duration controls and a root-role guard adapter. The package
also bundles a supported `PreToolUse` hook with status
`COVERED_PATH_GUARDRAIL`. It can deny covered local/MCP calls before dispatch
after trusted installation, but hosted paths, opt-outs, reauthorization gaps,
and non-spoofable root identity remain unresolved. See
`docs/DISPATCHER_ENFORCEMENT.md`.

No network client, MCP server, app connector, shell executor, or
arbitrary-command field is included.
