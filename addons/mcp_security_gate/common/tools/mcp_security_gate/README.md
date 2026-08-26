# mcp_security_gate (tool package)

Source-only, offline security gate for MCP servers. Deterministic static
validation over a declared risk manifest, with no runtime MCP client, no
network, no subprocess, and no dynamic loading.

## Layout

- `contracts.py`: closed enums (check ids, verdicts, reason codes, effect and
  posture vocabularies) and content-minimized dataclasses (`ToolManifest`,
  `RiskManifest`, `Finding`, `GateReport`) with strict `to/from_contract_dict`.
- `checks.py`: the closed set of pure per-risk static checks.
- `gate.py`: the evaluator `evaluate(manifest) -> GateReport`, computing a
  fail-closed disposition.
- `privacy_scan.py`: static scan forbidding network/process imports and
  endpoint/credential-shaped fixture content.
- `run_validation.py`: verifies schema/enum lockstep, fixture and coverage
  integrity, and the privacy scan, then runs the suites and prints
  `mcp_security_gate: PASS`.
- `schemas/`: closed JSON Schema 2020-12 documents, enum-locked to
  `contracts.py`.
- `fixtures/`: synthetic fake-MCP-server manifests, a clean-pass set and an
  adversarial set, each mapped to an executable test via a coverage map.
- `tests/`: stdlib `unittest` suites (`test_gate`, `test_checks`,
  `test_adversarial`).
- `docs/`: the check catalog and the integration/rollback runbook.

## Validate

```bash
PYTHONPATH=. python3 -B -m tools.mcp_security_gate.run_validation
```

## Evaluate a manifest

```python
from tools.mcp_security_gate.gate import evaluate_contract_dict

report = evaluate_contract_dict(manifest_dict)  # manifest_dict is static data
print(report.disposition.value)                 # "allow" or "block"
```
