# Deferred work

This tracked ledger is the canonical safety net for anything a pipeline filters,
skips, parks, blocks, or defers. A pipeline may report an item as deferred only
after `scripts/defer-work.sh` records it here successfully. The helper then makes
a best-effort, content-free GitHub issue projection so the work remains visible.

The file is authoritative; an issue or dashboard is a derivative roll-up. Each
record must name one opaque `dw-` ID with 16–64 lowercase hexadecimal characters
plus exactly one non-empty `Summary`, `Status` (`deferred` or `blocked`),
`Dependency`, and `Completion test`. The same ID and canonical record bytes are
replay-safe. Reusing an ID for different bytes fails closed.

Only repository-safe metadata belongs here. Never put credentials, regulated
data, private records, identities, production identifiers, parked payloads, or
competitive details in this ledger. Keep sensitive source material in its
approved private/encrypted store and record only an opaque safe reference. IDs
also appear in issue titles. Generate them independently from task content; do
not encode a name, topic, identity, or locator in them. The GitHub projection
contains only the ID and this canonical path; it never contains record content.

Example input file:

```text
Summary: Reconcile the synthetic import rejects
Status: deferred
Dependency: The input taxonomy is approved.
Completion test: The synthetic fixture imports with no parked rows.
```

Record it from the repository root:

```bash
bash scripts/defer-work.sh dw-0123456789abcdef < /path/to/record.md
```

Use `--local-only` when no issue projection is wanted. A tracker warning does
not undo a successful local record; replay the same ID and canonical bytes to
retry. A local error means the caller must stop and must not classify the item
as safely deferred. Every GitHub CLI phase has a 10-second deadline plus a
one-second termination grace period, so best-effort visibility cannot stall the
pipeline indefinitely.

The rename makes each successful update atomically visible inside one working
tree. It does not commit the change, flush hardware caches, reconcile concurrent
branches, or replace backups. Review and commit this tracked file with the work
that produced the deferral. An interrupted run may leave Git's
`defer-work.lock`; inspect the ledger and remove only that exact empty lock after
recovery. The helper never guesses that a lock is stale.

Cooperating writers in one working tree serialize through that lock; a hostile
same-user filesystem process remains outside this portable Bash boundary.
GitHub Issues has no atomic upsert, so exact-marker lookup minimizes duplicates
but cannot rule out a duplicate if creation succeeds and its response is lost.
An exact closed projection is reopened so deferred work returns to the visible
queue; an exact open projection is already current and remains unchanged.
