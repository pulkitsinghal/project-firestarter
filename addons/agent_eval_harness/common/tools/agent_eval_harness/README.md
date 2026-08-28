# Agent eval harness 0.1

This package is a source-only, deterministic evaluation harness for agent
outputs. Any stamped project can declare an evaluation CASE, hand a candidate
output plus its input fixtures to the reducer, and get back a RESULT whose
verdict is decided solely by deterministic, in-process, standard-library checks.
It makes no model call, opens no network connection, spawns no process, and
loads no caller-named module.

## Trust and data flow

```text
synthetic input fixture (opaque id + sha256 digest)
             |
             v
eval CASE: opaque id + versioned schema + input ref + closed blocking checks
             |
             v
candidate output: content-addressed evidence (id + sha256 digest + values)
             |          + optional advisory critique (quarantined)
             v
reducer: verify digests -> compute each check -> reduce blocking checks
             |
             v
eval RESULT: passed | failed | needs_review | unavailable  (+ result digest)
```

Candidate content crosses the boundary only as small comparable values keyed by
opaque field tokens, addressed by a `sha256:` digest that the reducer
recomputes and verifies. Raw prompts, transcripts, hosts, paths, credentials,
and private records are not fields in any contract.

## Closed vocabularies

- Check kinds: `exact-equals`, `subset`, `regex-match`, `numeric-threshold`,
  `ordered-contains`.
- Result states: `passed`, `failed`, `needs_review`, `unavailable`.

Blocking checks alone decide `passed`/`failed`. A non-blocking check only raises
`needs_review`. A missing input fixture or missing/tampered evidence yields
`unavailable`. The reducer never executes anything the case references; it only
compares already-reduced values.

## The model critique is advisory only

A candidate may carry an `advisoryCritique`. The reducer records whether it was
present and never reads it while scoring: the scoring function `_score` takes
only the computed check outcomes as its argument, so no critique field can reach
the verdict. A critique claiming `pass` on a failing case leaves the verdict
`failed`. See `harness.py` (`_score` and its call site) and
`docs/AGENT_EVAL_HARNESS.md`.

## Validation

The package uses only the Python standard library and synthetic fixtures:

```bash
PYTHONPATH=. python3 -B -m tools.agent_eval_harness.run_validation
```

See `docs/AGENT_EVAL_HARNESS.md` for the contract and invariants, and
`docs/INTEGRATION_AND_ROLLBACK.md` for adoption and removal.
