# Retain/remove manifest

## Retain

- Plugin source, repo-local marketplace, semantic version, changelog, and
  license.
- Operational skill, bridge, typed local MCP server, dispatcher/lifecycle hook
  adapters, contract reference, and user/operator docs.
- Deterministic unit, integration, adversarial, race, privacy, and crash tests.
- Source archive, Firestarter overlay bundle, narrow integration patch, hashes,
  and validation report.

## Remove after verification

- Ephemeral launch/recycle/handback request files that may contain reconstructed
  prompts.
- Synthetic test state directories and tickets.
- Python bytecode caches and extracted pinned reference trees.
- Ephemeral `.mcp-requests` contents; keep only the empty private directory when
  an active session still uses it.
- Task-owned integration worktrees after the later Firestarter PR merges and
  exact merged-default retest passes.

## Never remove automatically

- Firestarter SQLite authority or WAL/SHM files.
- A ticket or outbox record still needed to reconcile pending create/archive.
- Unique rollback evidence or a prior verified plugin release.
- Files or worktrees not proven to be owned by the current task.
