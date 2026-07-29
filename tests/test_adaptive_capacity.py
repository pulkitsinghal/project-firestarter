"""Audit-only adaptive-capacity and supervisor non-authority contract."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = (
    ROOT / "addons" / "orchestrator_session" / "common" / "orchestrator-control"
)
POLICY_PATH = CONTROL_ROOT / "adaptive_capacity_policy.py"
DOC_PATH = CONTROL_ROOT / "docs" / "ADAPTIVE_CAPACITY_AUDIT.md"
REQUEST_SCHEMA = (
    CONTROL_ROOT / "schemas" / "adaptive-capacity-audit.request.schema.json"
)
RESPONSE_SCHEMA = (
    CONTROL_ROOT / "schemas" / "adaptive-capacity-audit.response.schema.json"
)

SPEC = importlib.util.spec_from_file_location(
    "adaptive_capacity_policy", POLICY_PATH
)
assert SPEC and SPEC.loader
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


def request(
    *,
    load: float = 4.0,
    pressure: int = 20,
    swap: int = 0,
    observed: str = "2026-07-29T13:00:00Z",
    now: str = "2026-07-29T13:00:30Z",
    source: str = "synthetic-fixture",
) -> dict[str, object]:
    return {
        "interface_version": "1.0",
        "request_id": "audit-1",
        "snapshot_id": "snapshot-1",
        "source": {"kind": source, "evidence_ref": "synthetic host fixture"},
        "metrics": {
            "logical_cpus": 16,
            "load_1m": load,
            "memory_pressure_pct": pressure,
            "swap_used_mb": swap,
            "observed_at": observed,
        },
        "visible_limit": 4,
        "now": now,
    }


class AdaptiveCapacityAuditTests(unittest.TestCase):
    def test_healthy_snapshot_is_advisory_and_non_authorizing(self):
        result = policy.evaluate(request())["result"]
        self.assertEqual(result["visible_cap"], 4)
        self.assertEqual(result["internal_sublane_cap"], 2)
        self.assertEqual(result["heavy_local_cap"], 1)
        self.assertFalse(result["conservative"])
        for field in (
            "enforcement_applied",
            "reservation_created",
            "source_authority_verified",
            "service_actions_authorized",
        ):
            self.assertFalse(result[field])
        self.assertEqual(result["mode"], "audit")

    def test_high_load_serializes_heavy_without_contracting_visible_cap(self):
        result = policy.evaluate(request(load=16.0))["result"]
        self.assertEqual(result["visible_cap"], 4)
        self.assertEqual(result["internal_sublane_cap"], 1)
        self.assertEqual(result["heavy_local_cap"], 1)
        self.assertTrue(result["conservative"])

    def test_memory_or_swap_pressure_contracts_and_blocks_heavy(self):
        for pressure, swap in ((80, 0), (20, 1)):
            with self.subTest(pressure=pressure, swap=swap):
                result = policy.evaluate(request(pressure=pressure, swap=swap))[
                    "result"
                ]
                self.assertEqual(result["visible_cap"], 2)
                self.assertEqual(result["heavy_local_cap"], 0)

    def test_stale_boundary_is_computed_not_supplied(self):
        fresh = policy.evaluate(request(now="2026-07-29T13:01:00Z"))["result"]
        stale = policy.evaluate(request(now="2026-07-29T13:01:01Z"))["result"]
        self.assertEqual(fresh["age_seconds"], 60)
        self.assertEqual(fresh["reason"], "healthy local headroom")
        self.assertEqual(stale["age_seconds"], 61)
        self.assertEqual(stale["reason"], "stale metrics")
        self.assertEqual(stale["heavy_local_cap"], 0)

    def test_fractional_age_over_sixty_seconds_is_conservatively_stale(self):
        result = policy.evaluate(
            request(
                observed="2026-07-29T13:00:00.100000Z",
                now="2026-07-29T13:01:01Z",
            )
        )["result"]
        self.assertEqual(result["age_seconds"], 61)
        self.assertEqual(result["reason"], "stale metrics")

    def test_snapshot_digest_excludes_request_and_evaluation_context(self):
        first = request()
        second = request(now="2026-07-29T13:00:40Z")
        second["request_id"] = "audit-2"
        second["visible_limit"] = 2
        self.assertEqual(
            policy.evaluate(first)["result"]["snapshot_digest"],
            policy.evaluate(second)["result"]["snapshot_digest"],
        )

    def test_snapshot_digest_changes_with_observation(self):
        first = policy.evaluate(request())["result"]["snapshot_digest"]
        second = policy.evaluate(request(load=4.1))["result"]["snapshot_digest"]
        self.assertNotEqual(first, second)

    def test_future_observation_fails_closed(self):
        with self.assertRaises(policy.AuditInputError):
            policy.evaluate(
                request(
                    observed="2026-07-29T13:00:01Z",
                    now="2026-07-29T13:00:00Z",
                )
            )

    def test_unknown_fields_source_and_sensitive_refs_fail_closed(self):
        cases = []
        extra = request()
        extra["age_seconds"] = 0
        cases.append(extra)
        cases.append(request(source="trusted-local-probe"))
        for ref in ("/private/path", "owner@example.invalid", "https://host"):
            unsafe = request()
            unsafe["source"]["evidence_ref"] = ref
            cases.append(unsafe)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(
                policy.AuditInputError
            ):
                policy.evaluate(case)

    def test_boolean_nonfinite_negative_and_out_of_range_metrics_fail(self):
        mutations = [
            ("logical_cpus", True),
            ("logical_cpus", 0),
            ("load_1m", math.nan),
            ("load_1m", math.inf),
            ("load_1m", -0.1),
            ("memory_pressure_pct", True),
            ("memory_pressure_pct", 101),
            ("swap_used_mb", -1),
        ]
        for field, value in mutations:
            candidate = request()
            candidate["metrics"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(
                policy.AuditInputError
            ):
                policy.evaluate(candidate)

    def test_cli_is_byte_deterministic(self):
        body = json.dumps(request())
        command = [
            sys.executable,
            "-B",
            str(POLICY_PATH),
            "--request",
            "-",
        ]
        first = subprocess.run(
            command, input=body, text=True, capture_output=True, check=True
        ).stdout
        second = subprocess.run(
            command, input=body, text=True, capture_output=True, check=True
        ).stdout
        self.assertEqual(first, second)
        self.assertEqual(
            json.loads(first)["operation"], "evaluate-capacity-snapshot"
        )

    def test_cli_rejects_duplicate_json_keys(self):
        duplicate = json.dumps(request()).replace(
            '"request_id": "audit-1",',
            '"request_id": "audit-1", "request_id": "changed",',
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(POLICY_PATH),
                "--request",
                "-",
            ],
            input=duplicate,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stderr)["error"]["message"],
            "request contains duplicate object keys",
        )

    def test_file_errors_do_not_echo_paths(self):
        private_path = "/private/example/does-not-exist.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(POLICY_PATH),
                "--request",
                private_path,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        error = json.loads(completed.stderr)["error"]
        self.assertEqual(error["message"], "request file is unavailable")
        self.assertNotIn(private_path, completed.stderr)

    def test_linked_request_file_is_refused_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text(json.dumps(request()), encoding="utf-8")
            linked = root / "linked.json"
            linked.symlink_to(target)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(POLICY_PATH),
                    "--request",
                    str(linked),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stderr)["error"]["code"],
            "AUDIT_INPUT_REJECTED",
        )

    def test_schemas_are_closed_and_match_audit_constants(self):
        request_schema = json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8"))
        response_schema = json.loads(RESPONSE_SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(request_schema["additionalProperties"])
        self.assertFalse(response_schema["additionalProperties"])
        self.assertEqual(
            request_schema["properties"]["source"]["properties"]["kind"]["enum"],
            sorted(policy.SOURCE_KINDS),
        )
        result = response_schema["properties"]["result"]
        self.assertEqual(result["properties"]["mode"]["const"], "audit")
        for field in (
            "enforcement_applied",
            "reservation_created",
            "source_authority_verified",
            "service_actions_authorized",
        ):
            self.assertFalse(result["properties"][field]["const"])

    def test_supervisor_inventory_is_documented_as_stale_non_authority(self):
        documentation = DOC_PATH.read_text(encoding="utf-8")
        for expected in (
            "9655dcc04d53b5e48dbf50c1c963af9d79cc935a4071fd129ccb01e9b274c9e6",
            "3a4af3e78f68a81502b907a9d0c41be92e07092e7f3f0895319dd14f6e1948f5",
            "40 synthetic tests passed",
            "`dry_run: true`",
            "`permit_authority: false`",
            "`execution_authority: false`",
            "`executable: false`",
            "`live_service_actions: false`",
            "`network_listener: false`",
            "Its historical reduced inventory is not a capacity snapshot.",
            "No adaptive result can authorize a service action.",
        ):
            self.assertIn(expected, documentation)


if __name__ == "__main__":
    unittest.main()
