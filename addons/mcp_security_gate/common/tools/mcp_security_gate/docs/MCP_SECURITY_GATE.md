# MCP security gate: closed check catalog and fail-closed semantics

The gate evaluates a static, synthetic **risk manifest** describing one MCP
server (or tool set) and returns a set of typed findings plus an overall
disposition. It performs deterministic static validation only. It never
imports, connects to, spawns, or executes anything a manifest names, and it
holds no MCP client, network client, or subprocess.

## Requirements, derived independently

The checks are derived from neutral public concepts only:

- The Model Context Protocol's public notions of tools, tool annotations, and
  structured tool output.
- JSON Schema 2020-12 closed-object validation (`additionalProperties: false`,
  enum-locked property values).
- NIST/OWASP-style security control concepts: least privilege, human
  confirmation for irreversible actions, confused-deputy avoidance, treating
  untrusted input as data, output encoding/sanitization, secret hygiene,
  resource bounding, and fail-closed degraded behavior.

No third-party gallery submission was cloned, downloaded, inspected, run, or
adapted. Fixtures are original synthetic data.

## The risk manifest (static data)

Server-scoped posture:

- `tokenPosture`: `audience-bound` | `blind-passthrough` | `unknown`.
- `grantedAudienceId` / `upstreamAudienceId`: opaque audience IDs. A match means
  the server forwards a token only to the audience it was granted for.
- `secretLogPosture`: `enforced` | `absent` | `unknown`.
- `degradedBehavior`: `fail-closed` | `fail-open` | `unknown`.

Per-tool posture (one entry per tool):

- `effect`: `read-only` | `idempotent-write` | `external-send` | `destructive` |
  `unknown`.
- `reversibility`: `read-only` | `reversible` | `compensating` | `irreversible` |
  `unknown`.
- `requiresConfirmation`: boolean.
- `annotationHandling`: `treated-as-data` | `trusted-as-instructions` | `unknown`.
- `outputSanitization`: `enforced` | `absent` | `unknown`.
- `timeoutMs`, `rateLimitPerMinute`, `maxResponseBytes`: a positive integer when
  bounded, or `null` when absent.

There are no URLs, hostnames, tokens, credentials, headers, request/response
bodies, or log lines anywhere in the manifest.

## Verdicts and disposition

Each check yields one `Finding` with a verdict from a closed set:

- `pass`: the posture satisfies the control.
- `fail`: the posture violates the control, or is missing/unknown/degraded.
- `not-applicable`: the control does not apply to this subject (for example,
  confirmation on a read-only tool).

The overall disposition is one of `allow` or `block` and **fails closed**:

```
disposition = block if any finding.verdict == fail else allow
```

A `not-applicable` verdict never allows on its own and never blocks. Because
every check maps a missing, unknown, or degraded posture to `fail`, an
incompletely declared server always blocks. See
`gate.py:evaluate` (the `disposition = Disposition.BLOCK if any(... is Verdict.FAIL ...) else Disposition.ALLOW`
expression) for the single decision point.

## Closed check catalog

| Check id | Scope | Verdict | Reason code |
| --- | --- | --- | --- |
| `effect-soundness` | tool | pass | `effect-declared-and-bounded` |
| | | fail | `effect-undeclared` (effect or reversibility `unknown`) |
| | | fail | `effect-reversibility-mismatch` (reversibility outside the effect's bounded envelope, e.g. a destructive tool claimed reversible) |
| `confirmation-required` | tool | pass | `confirmation-present` |
| | | fail | `confirmation-missing-for-irreversible` |
| | | not-applicable | `confirmation-not-required` (read-only / reversible) |
| `untrusted-annotation-handling` | tool | pass | `annotations-treated-as-data` |
| | | fail | `annotations-trusted-as-instructions` |
| | | fail | `annotation-posture-unknown` |
| `token-audience` | server | pass | `token-audience-bound` |
| | | fail | `token-blind-passthrough` |
| | | fail | `token-audience-mismatch` (confused deputy: upstream audience != granted) |
| | | fail | `token-posture-unknown` |
| `output-sanitization` | tool | pass | `output-sanitized` |
| | | fail | `output-unsanitized` |
| | | fail | `output-posture-unknown` |
| `secret-leakage` | server | pass | `secrets-redacted` |
| | | fail | `secret-in-logs` |
| | | fail | `secret-posture-unknown` |
| `timeout-present` | tool | pass | `timeout-bounded` |
| | | fail | `timeout-absent` (null or non-positive) |
| `rate-limit-present` | tool | pass | `rate-limit-bounded` |
| | | fail | `rate-limit-absent` |
| `size-cap-present` | tool | pass | `size-cap-bounded` |
| | | fail | `size-cap-absent` |
| `degraded-fail-closed` | server | pass | `degraded-fails-closed` |
| | | fail | `degraded-fails-open` |
| | | fail | `degraded-posture-unknown` |

### Effect / reversibility envelope

`effect-soundness` requires reversibility to sit inside the bounded envelope for
the declared effect:

- `read-only` -> `read-only`
- `idempotent-write` -> `reversible` or `compensating`
- `external-send` -> `compensating` or `irreversible`
- `destructive` -> `irreversible`

### Confirmation trigger

`confirmation-required` demands `requiresConfirmation == true` when the effect is
`external-send` or `destructive`, when reversibility is `irreversible`, or when
either the effect or reversibility is `unknown` (fail-closed). Otherwise the
check is `not-applicable`.

## Adversarial coverage

The adversarial fixture holds one otherwise-clean synthetic server per failure
mode, so exactly one check fails and the server blocks:

- undeclared destructive effect, and destructive-marked-reversible
- missing confirmation for an irreversible tool
- trusting untrusted annotations, and unknown annotation posture
- blind token passthrough, token audience mismatch, and unknown token posture
- unsanitized output
- secret in logs
- missing timeout, missing rate limit, missing size cap
- fail-open on degraded state, and unknown degraded posture

The clean fixture holds servers that pass every applicable check.

## Boundaries

- Python standard library only. No third-party dependencies.
- No network, no subprocess, no dynamic import. The evaluator never loads or
  runs code named by a manifest.
- Fake MCP servers exist only as static JSON fixtures (data), never as
  processes or sockets.
- Synthetic data only. No live credentials, endpoints, or captured traffic.
