# `agent_eval_harness` add-on

An opt-in, stack-agnostic, source-only, deterministic harness for evaluating
agent outputs. It ships a Python-stdlib reducer, a closed check vocabulary, a
closed result-state vocabulary, versioned JSON schemas (draft 2020-12,
`additionalProperties: false`), content-addressed evidence handling, a
quarantined advisory critique field, hermetic synthetic fixtures, and an
adversarial catalog.

The add-on makes no model call, opens no network connection, spawns no process,
and dynamically imports no caller-named module. A candidate's verdict is decided
only by deterministic, in-process checks over content-addressed evidence; the
optional model critique is recorded but is structurally excluded from scoring.

Enable it while stamping:

```bash
./bin/firestart.sh --defaults --set include_agent_eval_harness=yes
```

The generated project receives `tools/agent_eval_harness/`. Run its hermetic
validation before wiring any real case source or candidate producer:

```bash
PYTHONPATH=. python3 -B -m tools.agent_eval_harness.run_validation
```
