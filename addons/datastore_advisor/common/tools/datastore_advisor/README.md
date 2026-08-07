# Datastore advisor

Helps {{ project_name }} decide where its data should live — as a reasoned
argument with named tradeoffs, not a verdict. The full guide is
[docs/DATASTORE_ADVISOR.md](../../docs/DATASTORE_ADVISOR.md).

## Use it

```bash
# Interview, then print the decision record
python3 -m tools.datastore_advisor.cli

# Interview, then write the record where it belongs
python3 -m tools.datastore_advisor.cli -o docs/DATASTORE_DECISION.md

# Non-interactive (CI, or re-running after an answer changes)
python3 -m tools.datastore_advisor.cli --answers answers.json -o docs/DATASTORE_DECISION.md

# Raw recommendation as JSON
python3 -m tools.datastore_advisor.cli --answers answers.json --json

# Read one catalog entry, including what it is wrong for
python3 -m tools.datastore_advisor.cli --explain graph_db
```

Standard library only, Python 3.8+. No network, no install, no host SDK.

## Verify

```bash
python3 tools/datastore_advisor/selftest.py
```

Offline. Asserts that the default stays boring, that a sparse single-hop "graph"
is disqualified with its own numbers quoted back, that the edition check and the
restore drill are always emitted, and that every catalog entry declares what it is
wrong for.

## What it will tell you

Most of the time: **use PostgreSQL**. That is the honest answer for the majority
of projects, and the tool says it plainly rather than manufacturing sophistication.

It earns its keep in the minority of cases where it says something else — and in
the two checks it emits every single time:

- **Verify the edition you will actually run has the feature you are choosing it
  for.** Free and community editions routinely omit exactly the isolation,
  access-control, and backup features teams select an engine for. The failure is
  silent and surfaces in an audit.
- **Restore a backup into a working system, at least once.** A backup nobody has
  restored is not a backup.

## Answer file format

`--answers` takes a JSON object keyed by axis id (see `questions.json`). Use
`"unknown"` for anything you have not measured — it is a first-class answer and
comes back as a measurement task rather than a silent default.

```json
{
  "hold_data": "must_hold",
  "workload_shape": ["relational", "vector"],
  "scale": "hundreds_of_thousands",
  "traffic_profile": "mostly_idle",
  "isolation_model": "row_level",
  "isolation_is_the_reason": "no",
  "regulated": ["none"],
  "team": "solo",
  "backup_restore": "backup_only",
  "exit_tolerance": "prefer"
}
```

## Extending the catalog

Add an entry to `catalog.json`. It must declare `wrong_for` and `exit_cost` — the
self-test fails entries that only carry a pitch. Capability and pricing claims
belong in `citations` with a URL and the date you read it; if something is not
publicly documented, write that rather than guessing.
