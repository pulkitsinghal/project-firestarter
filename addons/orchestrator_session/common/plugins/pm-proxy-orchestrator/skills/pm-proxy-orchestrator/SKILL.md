---
name: pm-proxy-orchestrator
description: Enforce Firestarter's fail-closed cross-task control plane for agent-CLI task launches, PM-proxy approval routing, fenced worker receipts, typed handbacks, successor creation, and blocked-queue recycling. Use whenever the agent CLI creates or replenishes a visible task, records a durable scoped policy correction, asks an approval question, mutates under an orchestrated task, closes or archives a task, hands work to a successor, or reconciles duplicate repo/path ownership.
---

# PM Proxy Orchestrator

Treat the Firestarter SQLite authority as mandatory. Never call a visible-task
creation tool first and reconcile later.

Use `scripts/pm_proxy_bridge.py`. Pass an absolute Firestarter
`orchestrator_control.py`, an absolute initialized private state directory, and
absolute ticket paths. The wrapper invokes only a fixed command allowlist through
the current Python interpreter; it never executes caller-provided commands.

Read [contract.md](references/contract.md) before first use or when an interface
or receipt fails.

## Required sequence

1. The root dispatcher must call `root-action` before every root action and
   route protected filesystem, exec, browser, Sites, and task tools through
   `dispatcher_adapter.py`. A `DENY` response means the underlying call count
   must remain zero and a worker handoff is required. The bundled `PreToolUse`
   hook adds a `COVERED_PATH_GUARDRAIL` after trusted installation, but hosted
   paths, opt-outs, write-stdin reauthorization, and non-spoofable caller
   identity remain unproved. Never claim universal enforcement. Root must not
   spawn internal subagents; create only visible peer worker tasks, and never
   count root as worker capacity.
   In an enforced Codex root, use only the bundled `pm_proxy_*` MCP tools for
   verifier/control-plane work. General Bash, patch, filesystem, browser, Sites,
   and non-control MCP calls remain denied. The exact trusted project hook also
   requires a matching fresh ticket for covered task creation, a satisfied
   refill saga for covered archive, and a successful lifecycle-watchdog after
   every covered read/wait before another lifecycle or status action.
   After the complete live deny → typed MCP → reserved create/receipt →
   lifecycle debt/clear → close/refill/archive proof, leave root-role execution
   and have the owner record the bounded `COVERED_PATH_GUARDRAIL` adoption
   through the fixed `pm_proxy_bridge.py record-dispatcher-adoption` command.
   Dispatcher adoption is deliberately not an MCP tool: the orchestrator cannot
   approve its own enforcement evidence. Require status to report
   `covered_path_dispatcher_enforcement: true` while
   `platform_dispatcher_enforcement` and universal enforcement remain false.
   Never convert the bounded receipt into a universal claim.
2. Before trusting dispatcher adoption or launching/refilling, the owner must
   run `scripts/configure_runtime_pin.py` against one reviewed clean Firestarter
   worktree. The resulting private content pin covers the control CLI, version,
   schemas, root-role guard, and runtime verifier. Typed MCP calls may then omit
   `project_root`; an explicit mismatch or later drift fails closed. A plugin
   version update requires a new pin and a repeated live adoption proof.
3. Run `doctor`. Stop on any failure, including missing CLI, unsupported version
   or schemas, inaccessible/corrupt/locked state, or any quarantined rule.
4. Before filling capacity, reconcile live task facts and prepare a complete
   `recycle-queue` request. Run `prepare-launch` with both the recycle and launch
   requests. This command commits queue audit first, then calls Firestarter
   `prepare-launch`.
5. Continue only on exit `0`. Exit `2`, `3`, or `4` means no external creation.
   For `3`, reconcile the returned canonical task read-only.
6. Pass the returned `prompt` to the visible task-creation tool verbatim. Do not
   save, hash, summarize, or reconstruct it. Call the tool once for the returned
   `CREATE_THREAD` outbox action.
7. Immediately call `record-launch-receipt` with the external task ID, generated
   ticket, and bounded runtime-attestation file. Model and reasoning effort must
   reflect the launch surface. Use priority-tier source `runtime` only when the
   platform reports it; for desktop-app config verification use
   `config-verified`, never runtime. API-key priority-tier claims and unattested or
   conflicting runtime policy fail closed. If receipt recording fails, instruct
   the new task to remain read-only and reconcile/archive it; never allow
   mutation.
8. Reconcile every externally surfaced copy through `reconcile-external-task`.
   Only the external task ID in the canonical ticket receipt may proceed. A
   mirror without that receipt receives `STOP_READ_ONLY`, a zero-change
   handback, and archive instructions; it never counts toward capacity.
9. Before the worker's first mutation and at lease renewal, call `heartbeat`
   with the receipt-bearing ticket and the caller's external task ID. A missing,
   stale, fabricated, mismatched, mirrored, or
   fenced-out ticket stops mutation.
10. Route every approval through `classify-decision`. A notification API is
   reachable only after
   the returned route is `OWNER_GATE` and `owner_prompt_required` is true.
   Absorb `PM_PROXY`. Treat validation, unknown-action, and denial failures as a
   return to the orchestrator, never an owner prompt.
11. Close through `scripts/refill_saga.py close-and-refill`, never by a standalone
   archive path. Provide exact refs, typed checks, literal hosted-CI truth,
   privacy/deployment state, cleanup dispositions, observed terminal status,
   configured capacity, and complete runnable candidates. The saga records
   `CAPACITY_RELEASED`, recycles blocked work, and reserves the highest-value
   eligible successor before predecessor archive may complete.
12. Create each returned successor exactly once with its verbatim prompt, then
   call `refill_saga.py record-refill-receipt` with the same truthful runtime
   attestation boundary. Archive is forbidden until every reserved successor
   has an exact receipt or the saga durably records `EMPTY`, `OWNER_GATED`, or
   `CAPACITY_FULL` with evidence.
13. Run `refill_saga.py slot-status` for dashboard truth and
    `watchdog-refill` on periodic heartbeat/startup fallback. A positive runnable
    count with active-or-reserved below configured capacity is a failure state
    requiring immediate reconciliation.
14. For schema 1.3, call `lifecycle-watchdog` after every worker message, wait
    timeout, and before any status claim. Objective completion evidence cannot
    be overridden by a stale `running` label. Follow only the fenced
    terminalization result and exact interrupt receipt; release, blocked re-audit,
    successor receipt or terminal proof, and archive stay in that order.
15. For schema 1.2 duration state, use the receipt-fenced duration operations.
    A mirrored external task cannot heartbeat, hand back, or reclassify. Treat a
    failed setup row from `duration-schedule` as rolled back for selection and
    call `record-setup-failure` with the exact unreceipted ticket so Firestarter
    atomically poisons its create outbox, releases ownership, and optionally
    reserves the next candidate. Create/receipt the returned successor exactly
    once. The plugin cannot mutate a reservation created outside Firestarter;
    absent adopted rollback/dispatch integration for that external reservation,
    fail closed and leave the candidate deferred.
16. Pass a privacy-safe resource profile to
    `resource_scheduler.py` when host contention matters. Logical task lanes are
    not CPU processes: light work may run in parallel, while heavyweight work
    sharing one coarse contention group must serialize. Never put paths,
    identities, prompts, or secrets in a resource profile.
17. Run `recycle-queue` again on capacity, startup, dependency, evidence, or
    policy changes before launching lower-value work.

## Policy recording

Use `record-policy-rule` only for authenticated owner corrections or approved
scoped policy. Require the current expected policy revision. Keep
`directive.args` empty. Use aliases and bounded redacted summaries; never include
raw prompts, prompt hashes, commands, secrets, credentials, private records,
patient text, credential-bearing URLs, or arbitrary expressions.

## Fail-closed rules

- Never install or update a marketplace, personal plugin, or live agent-CLI config
  while operating this source artifact.
- Never infer compatibility. A major-version or required-schema mismatch fails.
- Never bypass duplicate/ownership exit `3`, quarantine, fence, lease, receipt,
  privacy, or evidence failures.
- Never downgrade an enumerated owner gate to PM proxy.
- Never persist a launch prompt or prompt digest in a ticket or ledger.
- Never call a shell, eval, template engine, hook, or command field from policy.
- Never describe the local control plane as global enforcement outside tasks
  that actually use this wrapper.
- Never describe assigned work as implemented, validated, merged, or deployed
  without the exact receipt/heartbeat/worker-handback evidence required by the
  root-role guard.
- Never derive capacity from manually maintained labels. Count Firestarter
  `RUNNING` receipts and `LAUNCH_PENDING` reservations, then combine them with
  durable handback/refill saga outcomes.
