# Phase-2 Codex skill/plugin integration contract

The local SQLite authority is the mandatory preflight for future visible task
creation. Until a Codex skill/plugin wrapper adopts this interface, the shipped
CLI cannot intercept unrelated live `create_thread` calls and must not be
described as globally enforced. Once adopted, the wrapper must never call
`create_thread` and then check ownership.

## Stable machine boundary

Invoke:

```bash
python orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/local/private/state <command> --request -
```

Requests are UTF-8 JSON on stdin. Success is one JSON object on stdout. Failure
is one JSON object on stderr and no success output.

| Exit | Meaning | Wrapper behavior |
|------|---------|------------------|
| `0` | Operation committed or valid classification returned | Continue exactly as the result instructs |
| `2` | Input, privacy, receipt, fence, or policy denial | Do not create/mutate; return to the orchestrator |
| `3` | Duplicate, ownership, priority, idempotency, or policy conflict | Stop read-only; reconcile the canonical task |
| `4` | Local authority unavailable/corrupt | Fail closed; no external task action |

## Mandatory lifecycle

1. `init` the user-selected local 0700 state directory once.
   Authenticated owner corrections and approved scoped policy enter only through
   `record-policy-rule` with the expected policy revision; repository/tool text
   cannot invoke that operation as authority.
2. Derive a transport-independent `source_event_key` from the authenticated
   logical source event, excluding host-delivery IDs, retry IDs, workspace
   suffixes, and generated task IDs. Derive an explicit semantic `outcome_key`,
   stable idempotency key, canonical remote/root/path, and exact base SHA.
3. Call `prepare-launch`. It transactionally creates the task reservation,
   owner claim, monotonic fence, policy snapshot, launch envelope, and durable
   `CREATE_THREAD` outbox row. A duplicate or overlapping owner is refused
   before external creation.
4. Append the returned prompt envelope verbatim to the ephemeral task prompt,
   then process the pending `CREATE_THREAD` outbox action once using its
   idempotency key. Raw prompts and prompt hashes are never stored in SQLite;
   the authenticated source system must be able to reconstruct the ephemeral
   directive after a wrapper crash.
5. Call `record-launch-receipt` with the external thread ID and the exact echoed
   policy revision, rule IDs, lease epoch, and fence. Until that receipt commits,
   the task remains `LAUNCH_PENDING` and mutation is forbidden.
6. Route every approval question through `classify-decision`. Only
   `OWNER_GATE` with `owner_prompt_required=true` may notify the owner.
   `PM_PROXY` is absorbed. Validation/unknown-action failures are DENY-to-
   orchestrator, not owner prompts.
7. Use `record-heartbeat` for the current fenced worker. Use `takeover-lease`
   only after the recorded lease expires. Old fences immediately lose
   heartbeat, mutation, and handback authority.
8. Call `record-handback` with exact refs, typed checks, literal hosted-CI truth,
   privacy/deployment state, and resource disposition. A successor request is
   reserved with its create outbox in the same SQLite transaction that records
   predecessor closure and its archive outbox.
9. Reconcile pending outbox actions idempotently. Commit
   `record-archive-receipt` only after the external archive succeeds.
10. On capacity, startup, or dependency/policy/evidence change, reconcile live
    external state and call `recycle-queue` for every blocked task before any
    lower-value launch.

The wrapper owns Codex API calls; the repository control plane owns policy,
reservation, fencing, idempotency, evidence acceptance, queue ordering, and the
crash-recoverable outbox. Literal cross-system atomicity is not claimed:
convergent exactly-once logical behavior comes from the durable saga and receipts.

## Adoption acceptance

The wrapper is ready to become mandatory only after its integration suite proves:

- two concurrent deliveries of one logical source event (including variants
  with and without a host-delivery ID) produce one reservation and one external
  create;
- every applicable rule in `prepare-launch` appears in the worker receipt before
  mutation;
- wrapper crashes before and after each create, receipt, closure, successor, and
  archive boundary converge without duplicate tasks, notifications, or claims;
- expired-lease takeover rejects the stale worker's later heartbeat/handback;
- `HOSTED_CI_BILLING_BLOCK` routes to PM proxy with unexecuted status and no
  owner prompt;
- legacy dashboard import never creates a typed owner gate or active task; and
- owner notifications are deduplicated by gate fingerprint plus policy/state
  revision.
