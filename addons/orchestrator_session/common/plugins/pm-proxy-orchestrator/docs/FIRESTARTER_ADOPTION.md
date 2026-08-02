# Firestarter adoption handoff

The source contract was initially read from merged Firestarter `master` commit
`ac60826b4dbb8622f56732538f44edfecb690eac`, especially
`addons/orchestrator_session/common/orchestrator-control/docs/PHASE2_PLUGIN_INTEGRATION.md`.

The integration was then rebased onto post-Router `master`
`a32741d7958eeff7fd49ccd979c44acccdc69d91`. The source artifact remains
independently usable with Firestarter interface 1.0. Schema 1.1 adds native
capacity sagas; schema 1.2 adds duration control and the root-role guard
contract; schema 1.3 adds runtime-policy receipts and lifecycle-watchdog
terminalization/refill fencing.

Integration procedure:

1. Create a clean isolated worktree from current `origin/master`.
2. Re-read repository instructions and the current Phase-2 contract.
3. Compare the current control-plane interface and schemas with this plugin's
   interface `1.0` compatibility checks.
4. Overlay the plugin under
   `addons/orchestrator_session/common/plugins/pm-proxy-orchestrator/` and its
   marketplace under
   `addons/orchestrator_session/common/.agents/plugins/marketplace.json`.
5. Preserve the explicit manifest binding from `mcpServers` to `./.mcp.json`;
   do not add an overlay-level `.codex/hooks.json` or trusted root-role
   assignment.
6. Review the current-master integration bundle supplied with this artifact.
7. Add exact byte-preservation checks for the plugin and marketplace, an exact
   MCP-manifest contract, and an assertion that the overlay cannot auto-arm a
   project hook.
8. Run the plugin suite, plugin and skill validators, Firestarter's control-plane
   suite, every declared stack stamp, token leak/preservation checks, shell
   syntax, and generated-project plugin validation.
9. Review, commit, push, open a normal PR, observe hosted checks literally,
   merge only when eligible, and rerun the full gate on exact merged `master`.

The local bridge alone cannot intercept unrelated `create_thread` or other root
calls. The exact trusted project hook now admits covered create/archive calls
only through matching Firestarter ticket/refill evidence, and its lifecycle
debt fence requires a successful typed watchdog after covered worker reads and
waits. The local stdio MCP surface gives the root fixed control-plane operations
without general shell access. Hosted paths, platform opt-outs, write-stdin
reauthorization, and universal caller identity remain gaps.
Repository merge, marketplace availability, installation, active hook trust,
dispatcher adoption, and a real host E2E denial are separate proofs. Use status
`COVERED_PATH_GUARDRAIL`, never universal enforcement. Setup-failure selection
is available at schema 1.2, but rollback of
a reservation created outside Firestarter remains unsupported and must fail
closed until a host adapter owns that transaction.
