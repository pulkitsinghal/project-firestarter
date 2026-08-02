"""Contract coverage for the stack-agnostic orchestrator-session add-on."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "firestarter.config.json"
GENERATOR = ROOT / "bin" / "generate.py"
ADDON = ROOT / "addons" / "orchestrator_session" / "common"
CANONICAL_BILL = ADDON / "ORCHESTRATOR_BILL_OF_RIGHTS.md"
REQUIRED_FILES = {
    ".codex/config.toml",
    "AGENTS.orchestrator.md",
    "ORCHESTRATOR_BILL_OF_RIGHTS.md",
    "ORCHESTRATOR_PROMPT.md",
    "decisions-board/decisions.html",
    "decisions-board/decisions.json",
    "docs/ORCHESTRATOR_SESSION.md",
    "bin/verify-orchestrator-runtime.py",
    "orchestrator-control/README.md",
    "orchestrator-control/VERSION",
    "orchestrator-control/adaptive_capacity_policy.py",
    "orchestrator-control/dashboard.html",
    "orchestrator-control/docs/ADAPTIVE_CAPACITY_AUDIT.md",
    "orchestrator-control/docs/PHASE2_PLUGIN_INTEGRATION.md",
    "orchestrator-control/orchestrator_control.py",
    "orchestrator-control/policy-ledger.json",
    "orchestrator-control/root_role_guard.py",
    "orchestrator-control/schemas/adaptive-capacity-audit.request.schema.json",
    "orchestrator-control/schemas/adaptive-capacity-audit.response.schema.json",
    "orchestrator-control/schemas/classify-decision.request.schema.json",
    "orchestrator-control/schemas/classify-decision.response.schema.json",
    "orchestrator-control/schemas/capacity-watchdog.request.schema.json",
    "orchestrator-control/schemas/capacity-watchdog.response.schema.json",
    "orchestrator-control/schemas/duration-estimate.request.schema.json",
    "orchestrator-control/schemas/duration-estimate.response.schema.json",
    "orchestrator-control/schemas/duration-schedule.request.schema.json",
    "orchestrator-control/schemas/duration-schedule.response.schema.json",
    "orchestrator-control/schemas/dispatcher-adoption.request.schema.json",
    "orchestrator-control/schemas/dispatcher-adoption.response.schema.json",
    "orchestrator-control/schemas/effective-rules.request.schema.json",
    "orchestrator-control/schemas/heartbeat.request.schema.json",
    "orchestrator-control/schemas/lifecycle-watchdog.request.schema.json",
    "orchestrator-control/schemas/lifecycle-watchdog.response.schema.json",
    "orchestrator-control/schemas/machine-response.schema.json",
    "orchestrator-control/schemas/migrate-decisions.request.schema.json",
    "orchestrator-control/schemas/policy-ledger.schema.json",
    "orchestrator-control/schemas/prepare-launch.request.schema.json",
    "orchestrator-control/schemas/prepare-launch.response.schema.json",
    "orchestrator-control/schemas/receipt.request.schema.json",
    "orchestrator-control/schemas/reconcile-external-task.request.schema.json",
    "orchestrator-control/schemas/reconcile-external-task.response.schema.json",
    "orchestrator-control/schemas/record-handback.request.schema.json",
    "orchestrator-control/schemas/record-handback.response.schema.json",
    "orchestrator-control/schemas/record-duration-observation.request.schema.json",
    "orchestrator-control/schemas/record-duration-observation.response.schema.json",
    "orchestrator-control/schemas/record-duration-progress.request.schema.json",
    "orchestrator-control/schemas/record-duration-progress.response.schema.json",
    "orchestrator-control/schemas/record-policy-rule.request.schema.json",
    "orchestrator-control/schemas/recycle-queue.request.schema.json",
    "orchestrator-control/schemas/recycle-queue.response.schema.json",
    "orchestrator-control/schemas/root-role-guard.request.schema.json",
    "orchestrator-control/schemas/root-role-guard.response.schema.json",
    "orchestrator-control/schemas/shared.schema.json",
    "orchestrator-control/schemas/takeover-lease.request.schema.json",
    ".agents/plugins/marketplace.json",
    "plugins/pm-proxy-orchestrator/.mcp.json",
    "plugins/pm-proxy-orchestrator/.codex-plugin/plugin.json",
    "plugins/pm-proxy-orchestrator/hooks/hooks.json",
    "plugins/pm-proxy-orchestrator/hooks/post_tool_use_lifecycle.py",
    "plugins/pm-proxy-orchestrator/hooks/pre_tool_use_root_guard.py",
    "plugins/pm-proxy-orchestrator/scripts/mcp_server.py",
    "plugins/pm-proxy-orchestrator/skills/pm-proxy-orchestrator/SKILL.md",
    "plugins/pm-proxy-orchestrator/skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py",
    "plugins/pm-proxy-orchestrator/skills/pm-proxy-orchestrator/scripts/refill_saga.py",
}
REQUIRED_FAILURE_PREVENTION_CLAUSES = {
    "blocked_queue": "Blocked work is a reviewable queue, not permanent parking.",
    "blocked_queue_priority": (
        "resume the highest-value safely unblocked task first."
    ),
    "canonical_owner": "Each repository and mutable path has one canonical owner.",
    "closure_transaction": (
        "Task closure and successor or replacement creation are one lifecycle "
        "transaction."
    ),
    "closure_refill_capacity": (
        "Whenever runnable work exists, active-or-reserved slots equal configured"
    ),
    "duplicate_stop": (
        "the duplicate lane stops at read-only\n"
        "  reconciliation, returns any unique evidence, performs no write, and archives."
    ),
    "external_mirror": (
        "dashboards show only the canonical receipt-backed owner."
    ),
    "fidelity": "Orchestration fidelity outranks opportunistic local execution.",
    "root_role": (
        "The root orchestrator is a control-plane role, not a task worker."
    ),
    "root_preflight": (
        "Before every\n"
        "root tool call or action, classify the proposal as orchestration or task\n"
        "execution through the `ROOT_ORCHESTRATOR_ROLE` guard."
    ),
    "root_delegates_execution": (
        "Root must not inspect a task domain or repository,\n"
        "design, code, test, estimate, deploy, or clean up when a delegable worker lane\n"
        "exists."
    ),
    "root_control_plane_invariant": (
        "This is a control-plane invariant, not prompt etiquette."
    ),
    "root_coordination_only": (
        "Whenever an eligible\n"
        "worker slot exists, root is coordination-only."
    ),
    "missed_delegation_denied": (
        "A missed delegation followed by\n"
        "root inspection or direct work is a denied control-plane action."
    ),
    "pm_proxy_refill_not_blocked": (
        "Root must not\n"
        "claim `blocked` while a PM-proxy-safe queue refill or worker handoff is\n"
        "available."
    ),
    "typed_root_exception": (
        "The only direct-execution escape hatch is a typed\n"
        "`ROOT_EXECUTION_EXCEPTION` receipt"
    ),
    "source_not_runtime_enforcement": (
        "the standalone source module\n"
        "cannot intercept tools by itself."
    ),
    "dispatcher_interposition": (
        "every filesystem, process execution, browser, Sites, and task-management tool"
    ),
    "root_excluded_from_capacity": "Root never occupies worker capacity.",
    "root_no_internal_subagents": (
        "Root must never spawn an internal or nested subagent."
    ),
    "visible_peer_workers": "Every worker is a visible\npeer task",
    "owner_gate_before_notification": (
        "An owner\n"
        "notification is unreachable unless\n"
        "`classify-decision` has returned a current typed `OWNER_GATE`"
    ),
    "dashboard_freshness": (
        "It must show the receipt-backed\n"
        "status source, evaluation time, and freshness/staleness marker;"
    ),
    "truthful_worker_status": (
        "`validated` requires a worker handback with validation evidence;"
    ),
    "send_message_not_completion": (
        "A delegation or `send_message` event proves none of `implemented`, `tested`, or\n"
        "`complete`."
    ),
    "capacity_requires_receipt": (
        "only the canonical external task with its fresh exact launch receipt is active."
    ),
    "duration_bucket_bounds": (
        "`seconds` is 0–<60 seconds, `5m` is 60–<450, `10m` is 450–<750,"
    ),
    "duration_non_runtime": (
        "`blocked` and `waiting` are non-runtime states, never duration buckets."
    ),
    "duration_launch_envelope": (
        "Every launch envelope carries a monotonically versioned duration estimate,"
    ),
    "duration_measurements": (
        "Measure actual active work separately from queue, setup, tool wait, external\n"
        "  wait, and total wall time."
    ),
    "duration_unknown_null": (
        "An unknown component is `null`, never an inferred zero."
    ),
    "duration_rollover": (
        "atomically move the\n"
        "  same fenced worker to the longer lane without restart, release the shorter\n"
        "  lane, preserve ownership, and emit an evidence-only calibration event."
    ),
    "duration_learning_floor": (
        "Learn automatic priors only from a bounded rolling window of at least five\n"
        "  completed samples for the same coarse task family, tool family, and\n"
        "  environment class."
    ),
    "duration_schedule_fairness": (
        "Age eligible queued work fairly, reserve short-lane capacity against\n"
        "  starvation, and cap concurrent `45m`/`60m+` work."
    ),
    "duration_setup_truth": (
        "Queued setup occupies a\n"
        "  reservation but is not active."
    ),
    "duration_failure_retry": (
        "A failed create or setup rolls its reservation\n"
        "  back and immediately re-runs selection for the next eligible lane."
    ),
    "duration_empty_truth": (
        "`EMPTY`\n"
        "  means the complete current candidate set contains no eligible work;"
    ),
    "duration_privacy": (
        "Duration calibration stores only coarse families, bucket/version/confidence,"
    ),
    "launch_envelope": (
        "Every task launch envelope includes all applicable standing decisions,"
    ),
    "ledger_before_prompt": (
        "Consult the PM-proxy decision ledger before any approval prompt."
    ),
    "prompt_boundary": "Prompts are reserved for genuine owner gates.",
    "resource_return": (
        "every completed lane releases its task-owned resources and returns its\n"
        "evidence to the orchestrator."
    ),
    "exact_closure_sequence": (
        "handback → capacity release → blocked-work re-audit → exact successor launch"
    ),
    "transactional_reservation": (
        "Reserve the task, all ownership claims, and\n"
        "  its create outbox in one transaction before external task creation"
    ),
    "fencing": (
        "monotonically increasing fence so the prior worker cannot heartbeat, mutate,"
    ),
    "privacy_safe_policy": (
        "Never\n"
        "persist a raw conversation, prompt, secret, private value, stdout, diff, or"
    ),
}


class OrchestratorSessionContractTests(unittest.TestCase):
    def test_repo_local_plugin_marketplace_and_validation_suite(self) -> None:
        marketplace_path = ADDON / ".agents" / "plugins" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        self.assertEqual("project-firestarter", marketplace["name"])
        self.assertEqual(1, len(marketplace["plugins"]))
        entry = marketplace["plugins"][0]
        self.assertEqual("pm-proxy-orchestrator", entry["name"])
        self.assertEqual(
            {
                "source": "local",
                "path": "./plugins/pm-proxy-orchestrator",
            },
            entry["source"],
        )
        plugin_root = ADDON / "plugins" / "pm-proxy-orchestrator"
        manifest = json.loads(
            (plugin_root / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(entry["name"], manifest["name"])
        self.assertRegex(
            manifest["version"],
            r"^0\.3\.1(?:\+codex\.\d{14})?$",
        )
        self.assertEqual("./skills/", manifest["skills"])
        self.assertEqual("./.mcp.json", manifest["mcpServers"])
        mcp = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "mcpServers": {
                    "pm-proxy-orchestrator": {
                        "command": "python3",
                        "args": ["scripts/mcp_server.py"],
                        "cwd": ".",
                    }
                }
            },
            mcp,
        )
        validated = subprocess.run(
            [sys.executable, str(plugin_root / "scripts" / "run_validation.py")],
            cwd=plugin_root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            0,
            validated.returncode,
            f"stdout={validated.stdout}\nstderr={validated.stderr}",
        )

    def test_every_declared_stack_stamps_the_exact_canonical_bill(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        stacks = config["stack"]
        self.assertIsInstance(stacks, list)
        self.assertGreater(len(stacks), 0)

        canonical_bytes = CANONICAL_BILL.read_bytes()
        canonical_text = canonical_bytes.decode("utf-8")
        self.assertEqual(
            "1.3.1",
            (ADDON / "orchestrator-control" / "VERSION")
            .read_text(encoding="utf-8")
            .strip(),
        )
        canonical_files = {
            path.relative_to(ADDON).as_posix(): path.read_bytes()
            for path in ADDON.rglob("*")
            if path.is_file()
        }
        self.assertNotIn(
            ".codex/hooks.json",
            canonical_files,
            "the add-on must not arm root enforcement before plugin MCP discovery",
        )
        self.assertTrue(REQUIRED_FILES <= canonical_files.keys())
        for clause, required_text in REQUIRED_FAILURE_PREVENTION_CLAUSES.items():
            with self.subTest(clause=clause):
                self.assertIn(required_text, canonical_text)

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            for stack in stacks:
                with self.subTest(stack=stack):
                    output = output_root / stack
                    subprocess.run(
                        [
                            sys.executable,
                            str(GENERATOR),
                            "--defaults",
                            "--set",
                            f"stack={stack}",
                            "--set",
                            "include_orchestrator_session=yes",
                            "--output",
                            str(output),
                        ],
                        cwd=ROOT,
                        check=True,
                        capture_output=True,
                        text=True,
                    )

                    stamped = {
                        path.relative_to(output).as_posix()
                        for path in output.rglob("*")
                        if path.is_file()
                    }
                    self.assertTrue(
                        REQUIRED_FILES <= stamped,
                        f"{stack} missing {sorted(REQUIRED_FILES - stamped)}",
                    )
                    self.assertEqual(
                        canonical_bytes,
                        (output / "ORCHESTRATOR_BILL_OF_RIGHTS.md").read_bytes(),
                        f"{stack} changed the canonical Bill while stamping",
                    )
                    for relative, expected_bytes in canonical_files.items():
                        with self.subTest(stack=stack, file=relative):
                            self.assertEqual(
                                expected_bytes,
                                (output / relative).read_bytes(),
                                f"{stack} changed {relative} while stamping",
                            )

                    prompt = (output / "ORCHESTRATOR_PROMPT.md").read_text(
                        encoding="utf-8"
                    )
                    agents = (output / "AGENTS.orchestrator.md").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn(
                        "ORCHESTRATOR_BILL_OF_RIGHTS.md",
                        prompt,
                    )
                    self.assertIn(
                        "ORCHESTRATOR_BILL_OF_RIGHTS.md",
                        agents,
                    )
                    self.assertLess(len(prompt), 1_000)
                    self.assertLess(len(agents), 1_500)

                    state = output_root / f"{stack}-control-state"
                    control = output / "orchestrator-control" / "orchestrator_control.py"
                    initialized = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(control),
                            "--state-dir",
                            str(state),
                            "init",
                            "--now",
                            "2026-07-28T18:00:00Z",
                        ],
                        cwd=output,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    self.assertTrue(json.loads(initialized.stdout)["ok"])
                    status = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(control),
                            "--state-dir",
                            str(state),
                            "status",
                        ],
                        cwd=output,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual("1.3", json.loads(status.stdout)["result"]["schema_version"])


if __name__ == "__main__":
    unittest.main()
