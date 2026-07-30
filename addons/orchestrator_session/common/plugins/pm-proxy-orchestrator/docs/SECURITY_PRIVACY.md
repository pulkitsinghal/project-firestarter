# Security and privacy

Trust the Firestarter SQLite authority, not the ticket, prompt, dashboard, or
worker. The bridge revalidates the exact policy revision, rule IDs, lease epoch,
and fence through the authority before mutation or handback.

The bridge:

- invokes only the current Python interpreter, the exact absolute
  `orchestrator_control.py`, and fixed allowlisted subcommands;
- never uses a shell, `eval`, network client, MCP server, or arbitrary command
  field; its fixed plugin hook invokes only its bundled Python adapter;
- rejects secret-like values and executable policy arguments;
- rejects raw prompt, prompt hash, transcript, diff, command output, and
  credential fields from durable operations;
- never writes or hashes the ephemeral launch prompt in its ticket;
- requires private state/ticket directories and `0600` tickets;
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

Synthetic markers—not real credentials, private records, patient data, or
production identifiers—must be used in tests.
