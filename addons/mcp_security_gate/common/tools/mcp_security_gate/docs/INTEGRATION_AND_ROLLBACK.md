# Integration and rollback

The `mcp_security_gate` add-on is opt-in and disabled by default. A generated
project only receives `tools/mcp_security_gate/` when it is stamped with
`include_mcp_security_gate=yes`.

## Enable

```bash
./bin/firestart.sh --defaults --set include_mcp_security_gate=yes
```

## Validate before wiring

Always run the hermetic validation in the generated project first:

```bash
PYTHONPATH=. python3 -B -m tools.mcp_security_gate.run_validation
```

Expected terminal line: `mcp_security_gate: PASS`.

## Integrate

The gate is a pure library. Integrate it at the point where your application
registers or exposes MCP servers/tools (for example a gateway target registry,
a tool-catalog loader, or a CI policy step):

1. Have an operator author a static risk manifest for the server, using opaque
   IDs and the closed enums only. Do not put endpoints, tokens, credentials, or
   payloads into the manifest.
2. Validate the manifest object against `schemas/risk-manifest-1.0.schema.json`
   with your JSON-schema validator of choice (the package itself parses via
   `RiskManifest.from_contract_dict`, which enforces the same closed shape).
3. Call the evaluator:

   ```python
   from tools.mcp_security_gate.gate import evaluate_contract_dict

   report = evaluate_contract_dict(manifest_dict)
   if report.disposition.value == "block":
       # refuse registration / fail the CI gate; inspect report.findings
       ...
   ```

4. Persist or log `report.to_contract_dict()` (it matches
   `schemas/gate-report-1.0.schema.json`). The report contains only check ids,
   verdicts, reason codes, and opaque subject IDs.

The gate is advisory to your control flow: it returns a decision, it does not
enforce one. It never contacts the server it describes.

## Fail-closed posture

Treat a `block` disposition, or any inability to produce a report, as deny.
Because every unknown or degraded posture maps to a `fail`, a server that is not
fully and soundly declared always blocks. Do not add an "allow on unknown" path.

## Rollback

- Runtime: stop calling the evaluator. It has no persistent state, no
  background task, no network client, and no subprocess, so nothing needs to be
  drained or torn down.
- Generation: re-stamp with `include_mcp_security_gate=no` (the default). The
  next generated project omits `tools/mcp_security_gate/` entirely.
- The add-on is self-contained under `tools/mcp_security_gate/`; deleting that
  directory fully removes it.
