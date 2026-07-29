# Service supervisor 0.2 permit verifier

## Boundary

The permit verifier is a source-only authorization boundary. It parses a
strict local-ai adapter plan, confirms its deterministic SHA-256 digest, and
verifies a signed PM permit before atomically consuming that permit's nonce. It
then returns a separately authenticated, short-lived receipt whose decision is
`AUTHORIZED_FOR_EXECUTOR_HANDOFF`. A different, separately reviewed component
would still have to execute anything.

This package does not provide that component. It has no OS executor, shell,
subprocess, network client, listener, Docker API/socket, `launchctl` invocation,
Compose invocation, or Ollama request path. Exact argv and HTTP values are data
under validation, not commands issued by this module.

The local-ai contract pin in `local-ai-contract-pin.json` is part of the trust
boundary. It pins merged local-ai main
`3986befb06106b66795444d54f8513ead83f76b0`, the schema, catalog,
observations, plan, result, deliberately unsigned permit fixture, and canonical
plan digest. Exact byte copies of all five producer fixtures live under
`compatibility/local-ai/`. `load_contract_pin()` rejects provisional,
malformed, oversized, non-regular, and symlinked pins; callers pass the loaded
schema and catalog digests into `PermitVerifier`.

## Typed producer seam

The merged producer root is exactly:

```text
schema_version, kind, supervisor_contract_version, target_service_id,
intent, dry_run, steps, plan_digest
```

Its current constants are schema `1`, kind `local-ai-adapter-plan`, producer
contract `0.1.0`, and `dry_run:true`. The digest is lowercase SHA-256 over the
ASCII bytes from Python `json.dumps` with `sort_keys=True`,
`separators=(",",":")`, and `ensure_ascii=True`, after omitting
`plan_digest`.

Each step has the exact keys `sequence`, `service_id`, `adapter`, `operation`,
`resource_key`, `argv`, `http_request`, `readiness`, and `rollback`.

- launchd argv starts with exact `/bin/launchctl` and one allowlisted semantic
  operation. Targets and plist paths must match the resource key.
- Compose argv starts with one of two exact Docker binary paths and the exact
  `compose --project-name ... --file ... start|stop ...` token shape.
- Ollama uses no argv. It permits only a POST to loopback port 11434 at
  `/api/generate`, with an exact model/keep-alive JSON object and no stream for
  unload.
- Readiness is a bounded loopback GET with an exact expectation.
- Rollback is a typed inverse operation. It is included in the plan digest but
  is not authorized by an apply permit.

Unknown keys, adapters, operations, tokens, paths, URLs, reordered or duplicate
steps, mismatched resources, non-inverse rollback, and digest changes refuse.

Result validation is bound to the exact plan digest and accepts only the
producer's result fields and bounded status/error vocabulary. A success cannot
claim partial readiness. Failed rollback remains a failure and never becomes
authorization evidence.

## Permit authority

The unsigned producer compatibility permit is not accepted. Firestarter requires
an exact HMAC-SHA256 permit with:

- policy and key ID;
- permit ID, issue time, strict expiry, and high-entropy nonce;
- exact plan digest, target service, intent, operations, and adapters;
- exact `apply` or `rollback` authorization phase;
- exact merged producer-schema and catalog digests;
- exact executor and state generations;
- an exact service-and-intent plan digest pre-derived from the reviewed catalog;
- a signature over every field except the signature itself.

The trusted keyring is injected in memory. This package defines no secret file,
environment variable, signing CLI, or key-distribution mechanism. Key custody
and issuer operation remain a separate PM-proxy integration review.

Clock policy rejects permits issued beyond the bounded skew, permits with
invalid or overlong lifetimes, and permits at or after expiry. Apply and
rollback need different signed phases and nonces. A forward permit cannot be
reused for rollback.

## Authenticated handoff receipt

The former bare decision object is not out-of-process authority. A mode-`0600`
Unix socket alone cannot distinguish a forged same-user client. After the PM
permit transaction commits, the verifier returns an exact
`execution-handoff-receipt` with:

- receipt version, ID, independent nonce, issue/expiry, verifier instance, and
  receipt key ID;
- decision, policy, service, intent, apply/rollback phase, exact plan digest,
  sorted action set, and sorted adapter set;
- consumed permit ID and fingerprint;
- producer schema, catalog, executor generation, and state generation;
- verifier-artifact and contract-pin digests;
- rollback authorization and a separate HMAC-SHA256 signature.

The receipt signature covers compact sorted ASCII JSON with only `signature`
omitted. Its key must be distinct from every PM permit key. Its 256-bit nonce
is deterministically derived by HMAC from the receipt-only key, a fixed domain
separator, and the exact permit fingerprint; separate apply/rollback permits
therefore produce stable, distinct receipt nonces without reusing the PM nonce.
An out-of-process
broker must pin the receipt schema, accepted receipt key ID, verifier artifact,
and contract pin; verify the signature, exact scope/generations, and time
window; then atomically consume the independent receipt nonce in broker-owned
durable state. A receipt digest alone, the old decision shape, the unsigned
producer permit, or a protected socket is not authority.

Firestarter owns PM permit nonce consumption. The future broker owns handoff
receipt nonce consumption. Apply never implies cancellation or rollback:
rollback requires a distinct PM authorization phase, PM nonce, and signed
handoff receipt with a distinct receipt nonce.

The release schema is `execution-handoff-receipt.schema.json`. The matching
`compatibility/firestarter/execution-handoff-receipt-1.untrusted.synthetic.json`
uses a published synthetic test key and is never operational authority.

## Durable single use

The SQLite ledger is created mode `0600`, uses an immediate transaction for
nonce consumption, stores only SHA-256 nonce fingerprints, and persists
revocations. Symlinks, non-regular files, oversized state, unsupported schema
versions, and failed integrity checks refuse.

The authorization record commits before the signed handoff receipt is returned.
Concurrent copies therefore produce one winner and replay refusals. If the
process fails before commit, SQLite rolls the insertion back and a fresh
verifier can retry. Restarting does not make a consumed nonce reusable.
The exact plan/phase/catalog/executor/state generation is also single-use:
issuing a second nonce for an already consumed generation is a conflicting
permit, not a retry. A retry requires a newly reviewed state generation.

The deterministic snapshot is an audit/testing surface, not an executor input.
It excludes raw nonces, signatures, keys, commands, paths, URLs, models, and
private content.

## Telemetry

Permit telemetry has an exact bounded shape: decision/refusal, bounded reason
code, target service ID, intent, authorization phase, plan digest, and adapter
set. It contains no nonce, signature, key, argv, resource key, path, URL,
model, request/result content, or private payload.

## Tests

Run with the generated project's Docker-only toolchain:

```bash
docker run --rm -v "$PWD:/work:ro" -w /work python:3.12-slim \
  python -B -m unittest -v \
  tools.service_supervisor.tests.test_service_supervisor
```

The existing module entrypoint loads the permit-verifier suite so hosted and
generated-project validation cannot silently omit the 0.2 checks.
