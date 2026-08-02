# Security and privacy

Trust the Firestarter SQLite authority, not the ticket, prompt, dashboard, or
worker. The bridge revalidates the exact policy revision, rule IDs, lease epoch,
and fence through the authority before mutation or handback.

The bridge:

- invokes only the current Python interpreter, the exact absolute
  `orchestrator_control.py`, and fixed allowlisted subcommands;
- never uses a shell, `eval`, network client, or arbitrary command field; its
  fixed plugin hook invokes only bundled Python adapters;
- rejects secret-like values and executable policy arguments;
- rejects raw prompt, prompt hash, transcript, diff, command output, and
  credential fields from durable operations;
- never writes or hashes the ephemeral launch prompt in its ticket;
- requires the shared `~/.codex/orchestrator-state` root and each selected state
  directory to be `0700`, plus `0600` tickets;
- fails on missing CLI, incompatible versions/schemas, malformed machine
  responses, lock/corruption errors, quarantined rules, stale or missing
  receipts, and stale fencing;
- verifies owner-gate route and notification flag agree.
- requires an exact external task ID match before heartbeat, handback, or
  duration reclassification;
- requires exact launch model/effort and priority-tier provenance; config-derived
  desktop-app config verification is never labeled runtime, and API-key or
  unattested Fast claims fail closed;
- rejects direct terminal handback so capacity release cannot bypass the
  idempotent close/refill saga.

The root-role adapter invokes only the fixed Firestarter guard script through
the current Python interpreter. Its synthetic dispatcher E2E proves denied
filesystem, exec, browser, Sites, and task callables are never invoked. The
plugin's `PreToolUse` hook adds a covered-path denial boundary after trusted
installation, but it is not universal and has no non-spoofable root identity.
Installation, active hook trust, covered-path runtime proof, and platform
adoption must be proved separately.

The hook path treats availability failures as adversarial inputs. It never
waits indefinitely for an admission or lifecycle lock, refuses symlinked or
non-private lock files, records observation debt before dispatch, and keeps the
admission ledger bounded by pruning only entries whose authoritative ticket is
expired, receipted, or archive-complete. Corrupt live tickets remain a
fail-closed doctor/recovery condition; they are not silently discarded.

The bundled stdio MCP server is a narrow local adapter, not a general execution
surface. It accepts typed JSON objects, materializes them as `0600` ephemeral
files only inside an owner-only orchestrator state root, invokes fixed bridge or
refill operations without a shell, removes request files before returning, and
rejects state-directory escapes and unknown fields. Launch prompts remain
ephemeral and are never written to the durable ticket or lifecycle ledgers.

Synthetic markers—not real credentials, private records, patient data, or
production identifiers—must be used in tests.
