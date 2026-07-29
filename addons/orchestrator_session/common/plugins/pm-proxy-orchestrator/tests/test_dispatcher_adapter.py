from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

from tests.support import PLUGIN_ROOT, private_temp


ADAPTER_PATH = (
    PLUGIN_ROOT
    / "skills"
    / "pm-proxy-orchestrator"
    / "scripts"
    / "dispatcher_adapter.py"
)
SPEC = importlib.util.spec_from_file_location("dispatcher_adapter", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class DispatcherAdapterTest(unittest.TestCase):
    def test_real_root_guard_denies_every_task_domain_tool_before_execution(self):
        cli_value = os.environ.get("FIRESTARTER_CURRENT_CLI")
        if not cli_value:
            self.skipTest("set FIRESTARTER_CURRENT_CLI for adopted dispatcher E2E")
        guard = Path(cli_value).resolve().parent / "root_role_guard.py"
        self.assertTrue(guard.is_file())
        root = private_temp("pm-proxy-dispatch-")
        calls: list[str] = []
        tools = {
            name: (lambda _payload, tool=name: calls.append(tool))
            for name in ("filesystem", "exec", "browser", "sites", "task")
        }
        dispatcher = ADAPTER.GuardedDispatcher(
            guard_script=guard,
            audit_file=root / "root-role-audit.json",
            executors=tools,
        )
        task_actions = {
            "filesystem": "inspect_repository",
            "exec": "run_tests",
            "browser": "inspect_task_domain",
            "sites": "deploy",
            "task": "implement_code",
        }
        for index, (tool, action) in enumerate(task_actions.items()):
            result = dispatcher.dispatch(
                tool,
                {
                    "interface_version": "1.0",
                    "request_id": f"dispatcher-{index}",
                    "action_id": f"action-{index}",
                    "action_type": action,
                    "delegable_worker_available": True,
                    "evidence": [],
                },
            )
            self.assertFalse(result["executed"])
            self.assertEqual("DENY", result["guard"]["decision"])
        self.assertEqual([], calls)
        self.assertEqual(
            {name: 0 for name in tools},
            dispatcher.underlying_call_count,
        )
        invented_complete = dispatcher.dispatch(
            "task",
            {
                "interface_version": "1.0",
                "request_id": "invented-complete",
                "action_id": "invented-complete",
                "action_type": "synthesize_worker_evidence",
                "delegable_worker_available": True,
                "target_status": "implemented",
                "evidence": [],
            },
        )
        self.assertFalse(invented_complete["executed"])
        self.assertEqual(
            "UNTRUTHFUL_STATUS_FORBIDDEN",
            invented_complete["guard"]["reason_code"],
        )
        unproved_validated = dispatcher.dispatch(
            "task",
            {
                "interface_version": "1.0",
                "request_id": "unproved-validated",
                "action_id": "unproved-validated",
                "action_type": "synthesize_worker_evidence",
                "delegable_worker_available": True,
                "target_status": "validated",
                "evidence": [],
            },
        )
        self.assertFalse(unproved_validated["executed"])
        self.assertEqual(
            "WORKER_EVIDENCE_REQUIRED",
            unproved_validated["guard"]["reason_code"],
        )

    def test_both_observed_mirror_pairs_are_stopped_zero_change_and_archived(self):
        calls: list[tuple[str, str]] = []
        adapter = ADAPTER.AutoMaterializationAdapter(
            stop=lambda task: calls.append(("stop", task)),
            zero_change_handback=lambda task: calls.append(("handback", task)),
            archive=lambda task: calls.append(("archive", task)),
        )
        pairs = [
            ("019fabce-d109-canonical", "019fabce-d77d-mirror"),
            ("019fabe7-46b8-canonical", "019fabe7-4cba-mirror"),
        ]
        for canonical, mirror in pairs:
            result = adapter.reconcile(
                canonical_external_thread_id=canonical,
                observed_external_thread_id=mirror,
            )
            self.assertEqual("DUPLICATE_STOP", result["classification"])
            self.assertFalse(result["mutation_allowed"])
            self.assertFalse(result["capacity_eligible"])
        self.assertEqual(
            [
                action
                for _canonical, mirror in pairs
                for action in (
                    ("stop", mirror),
                    ("handback", mirror),
                    ("archive", mirror),
                )
            ],
            calls,
        )

    def test_notification_callable_is_unreachable_until_owner_gate(self):
        delivered: list[str] = []
        adapter = ADAPTER.OwnerNotificationAdapter(delivered.append)
        routine = adapter.deliver(
            {
                "classification": "PM_PROXY",
                "owner_prompt_required": False,
            },
            "routine",
        )
        denied = adapter.deliver(
            {
                "classification": "OWNER_GATE",
                "owner_prompt_required": False,
            },
            "downgraded",
        )
        self.assertFalse(routine["delivered"])
        self.assertFalse(denied["delivered"])
        self.assertEqual([], delivered)
        accepted = adapter.deliver(
            {
                "classification": "OWNER_GATE",
                "owner_prompt_required": True,
            },
            "gated",
        )
        self.assertTrue(accepted["delivered"])
        self.assertEqual(["gated"], delivered)
        self.assertEqual(1, adapter.call_count)


if __name__ == "__main__":
    unittest.main()
