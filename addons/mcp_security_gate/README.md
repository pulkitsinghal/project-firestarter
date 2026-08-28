# `mcp_security_gate` add-on

An opt-in, disabled-by-default, stack-agnostic, source-only security gate for
Model Context Protocol (MCP) servers. It ships a Python-stdlib evaluator, a
closed risk-manifest and gate-report schema pair, a deterministic set of static
risk checks, and hermetic synthetic fixtures of fake MCP servers.

The gate reasons only over a declared, static **risk manifest**: an MCP server's
tool set plus its declared security posture (effects and reversibility,
confirmation requirements, how tool-provided annotations are handled, token
audience/passthrough posture, output sanitization, secret/log hygiene, timeouts,
rate limits, response size caps, and degraded-state behavior). Every value is an
opaque ID or a closed enum. The manifest carries no endpoints, credentials,
tokens, request/response bodies, or log lines.

The evaluator is a pure function: manifest in, findings plus a fail-closed
disposition out. It never imports, connects to, spawns, or executes anything a
manifest names. The disposition **fails closed**: it allows only when every
applicable check passes; any missing, unknown, or degraded posture is a `fail`,
which blocks.

The add-on contains no MCP client or server, no network client, no subprocess,
no credential handling, and no deployment step. Fake MCP servers exist only as
static JSON fixtures (data), never as processes or sockets.

Enable it while stamping:

```bash
./bin/firestart.sh --defaults --set include_mcp_security_gate=yes
```

The generated project receives `tools/mcp_security_gate/`. Run its hermetic
validation before wiring the gate into any tool-registration or gateway path:

```bash
PYTHONPATH=. python3 -B -m tools.mcp_security_gate.run_validation
```

See `common/tools/mcp_security_gate/docs/MCP_SECURITY_GATE.md` for the closed
check catalog, reason codes, and fail-closed semantics, and
`docs/INTEGRATION_AND_ROLLBACK.md` for adoption and rollback.
