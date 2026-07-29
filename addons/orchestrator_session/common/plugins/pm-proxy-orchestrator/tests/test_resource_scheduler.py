from __future__ import annotations

import importlib.util
import unittest

from tests.support import PLUGIN_ROOT


PATH = (
    PLUGIN_ROOT
    / "skills"
    / "pm-proxy-orchestrator"
    / "scripts"
    / "resource_scheduler.py"
)
SPEC = importlib.util.spec_from_file_location("resource_scheduler", PATH)
assert SPEC is not None and SPEC.loader is not None
SCHEDULER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEDULER)


def profile(resource_class: str, group: str) -> dict[str, str]:
    return {
        "resource_class": resource_class,
        "contention_group": group,
        "cpu_intensity": "low" if resource_class == "light" else "high",
        "memory_intensity": "low" if resource_class == "light" else "high",
        "io_intensity": "moderate",
    }


class ResourceSchedulerTest(unittest.TestCase):
    def test_light_parallelism_does_not_confuse_lanes_with_processes(self):
        result = SCHEDULER.schedule(
            configured_lane_capacity=3,
            active_or_reserved=[],
            candidates=[
                {
                    "candidate_id": f"light-{index}",
                    "priority": 500 - index,
                    "queue_seconds": index,
                    "resource_profile": profile("light", "local-tools"),
                }
                for index in range(3)
            ],
        )
        self.assertEqual(
            ["light-0", "light-1", "light-2"],
            result["selected_candidate_ids"],
        )
        self.assertFalse(result["process_oversubscription_inferred"])

    def test_same_group_heavy_work_serializes_while_other_light_work_runs(self):
        result = SCHEDULER.schedule(
            configured_lane_capacity=3,
            active_or_reserved=[
                {
                    "candidate_id": "active-heavy",
                    "resource_profile": profile("heavy", "native-build"),
                }
            ],
            candidates=[
                {
                    "candidate_id": "second-heavy",
                    "priority": 900,
                    "queue_seconds": 100,
                    "resource_profile": profile("heavy", "native-build"),
                },
                {
                    "candidate_id": "light-a",
                    "priority": 800,
                    "queue_seconds": 80,
                    "resource_profile": profile("light", "native-build"),
                },
                {
                    "candidate_id": "light-b",
                    "priority": 700,
                    "queue_seconds": 70,
                    "resource_profile": profile("light", "local-tools"),
                },
            ],
        )
        self.assertEqual(
            ["light-a", "light-b"],
            result["selected_candidate_ids"],
        )
        self.assertIn(
            {
                "candidate_id": "second-heavy",
                "reason_code": "HEAVY_CONTENTION_SERIALIZED",
            },
            result["deferred"],
        )

    def test_resource_profile_rejects_paths_and_identity_like_groups(self):
        for unsafe in ("private/repo", "owner@example.invalid"):
            with self.assertRaises(ValueError):
                SCHEDULER.schedule(
                    configured_lane_capacity=1,
                    active_or_reserved=[],
                    candidates=[
                        {
                            "candidate_id": "unsafe",
                            "priority": 1,
                            "queue_seconds": 0,
                            "resource_profile": profile("light", unsafe),
                        }
                    ],
                )


if __name__ == "__main__":
    unittest.main()
