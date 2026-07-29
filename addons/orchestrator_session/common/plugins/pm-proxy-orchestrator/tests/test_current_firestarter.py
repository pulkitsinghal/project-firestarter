from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support import (
    BRIDGE,
    handback_request,
    iso,
    launch_request,
    private_temp,
    recycle_request,
    refill_request,
    write_json,
)


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REFILL = (
    PLUGIN_ROOT
    / "skills"
    / "pm-proxy-orchestrator"
    / "scripts"
    / "refill_saga.py"
)


class CurrentFirestarterIntegrationTest(unittest.TestCase):
    def test_schema_12_native_closure_and_external_mirror_boundary(self):
        cli_value = os.environ.get("FIRESTARTER_CURRENT_CLI")
        repo_value = os.environ.get("FIRESTARTER_CURRENT_REPO")
        if not cli_value or not repo_value:
            self.skipTest(
                "set FIRESTARTER_CURRENT_CLI and FIRESTARTER_CURRENT_REPO"
            )
        cli = Path(cli_value).resolve()
        repo = Path(repo_value).resolve()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        root = private_temp("pm-proxy-current-")
        state = root / "state"
        state.mkdir(mode=0o700)

        def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--cli",
                    str(cli),
                    "--state-dir",
                    str(state),
                    *args,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        initialized = run(BRIDGE, "init", "--now", iso())
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        doctor = run(BRIDGE, "doctor")
        self.assertEqual(0, doctor.returncode, doctor.stderr)
        self.assertEqual(
            "1.2",
            json.loads(doctor.stdout)["result"]["schema_version"],
        )
        root_request = write_json(
            root / "root-action.json",
            {
                "interface_version": "1.0",
                "request_id": "root-direct-work",
                "action_id": "root-direct-work",
                "action_type": "implement_code",
                "delegable_worker_available": True,
                "evidence": [],
            },
        )
        root_denied = run(
            BRIDGE,
            "root-action",
            "--request",
            str(root_request),
        )
        self.assertEqual(0, root_denied.returncode, root_denied.stderr)
        self.assertEqual(
            "DENY",
            json.loads(root_denied.stdout)["result"]["decision"],
        )
        schedule_request = write_json(
            root / "duration-schedule.json",
            {
                "interface_version": "1.0",
                "request_id": "setup-failure-recovery",
                "active_heavyweight": 0,
                "heavyweight_concurrency_cap": 1,
                "short_lane_available": True,
                "capacity_deficit": True,
                "candidates": [
                    {
                        "candidate_id": "failed-setup",
                        "bucket": "5m",
                        "runtime_state": "active",
                        "setup_state": "failed",
                        "priority": 900,
                        "queue_seconds": 100,
                    },
                    {
                        "candidate_id": "next-ready",
                        "bucket": "seconds",
                        "runtime_state": "active",
                        "setup_state": "ready",
                        "priority": 800,
                        "queue_seconds": 200,
                    },
                ],
                "now": iso(),
            },
        )
        scheduled = run(
            BRIDGE,
            "duration-schedule",
            "--request",
            str(schedule_request),
        )
        self.assertEqual(0, scheduled.returncode, scheduled.stderr)
        schedule_result = json.loads(scheduled.stdout)["result"]
        self.assertEqual("next-ready", schedule_result["selected_candidate_id"])
        self.assertEqual(
            1,
            schedule_result["reservation_summary"][
                "failed_setup_rollback_count"
            ],
        )
        self.assertFalse(schedule_result["owner_prompt_required"])
        setup_launch_value = launch_request(
            task_id="setup-failed-task",
            source_event_key="setup-failed-source",
            outcome_key="setup-failed-outcome",
            idempotency_key="setup-failed-idem",
            repo_root=str(repo),
            remote="https://github.com/pulkitsinghal/project-firestarter.git",
        )
        setup_launch_value["target"]["base_sha"] = head
        setup_launch_value["context"]["repo"] = (
            "github.com/pulkitsinghal/project-firestarter"
        )
        setup_recycle = write_json(
            root / "setup-recycle.json",
            recycle_request(request_id="setup-recycle"),
        )
        setup_launch = write_json(root / "setup-launch.json", setup_launch_value)
        setup_ticket = state / "setup-failed.ticket.json"
        setup_prepared = run(
            BRIDGE,
            "prepare-launch",
            "--recycle-request",
            str(setup_recycle),
            "--launch-request",
            str(setup_launch),
            "--ticket",
            str(setup_ticket),
        )
        self.assertEqual(0, setup_prepared.returncode, setup_prepared.stderr)
        setup_failure = write_json(
            root / "setup-failure.json",
            {
                "interface_version": "1.0",
                "request_id": "setup-failure",
                "reason_code": "synthetic-setup-failure",
                "evidence_refs": ["setup-failure-evidence"],
                "configured_capacity": 1,
                "runnable_queue_count": 0,
                "empty_outcome": "EMPTY",
                "blocked_audits": [],
                "successor_candidates": [],
                "now": iso(minutes=1),
            },
        )
        setup_recovered = run(
            BRIDGE,
            "record-setup-failure",
            "--ticket",
            str(setup_ticket),
            "--successor-ticket",
            str(state / "unused-successor.ticket.json"),
            "--request",
            str(setup_failure),
        )
        self.assertEqual(0, setup_recovered.returncode, setup_recovered.stderr)
        self.assertEqual(
            "FAILED",
            json.loads(setup_recovered.stdout)["result"]["state"],
        )
        marker = "SYNTHETIC_CURRENT_EPHEMERAL_FAQ_MARKER"
        predecessor = launch_request(
            task_id="current-faq",
            source_event_key="current-faq-source",
            outcome_key="current-faq-outcome",
            idempotency_key="current-faq-idem",
            prompt=marker,
            repo_root=str(repo),
            remote="https://github.com/pulkitsinghal/project-firestarter.git",
        )
        predecessor["target"]["base_sha"] = head
        predecessor["context"]["repo"] = (
            "github.com/pulkitsinghal/project-firestarter"
        )
        recycle = write_json(root / "recycle.json", recycle_request())
        launch = write_json(root / "launch.json", predecessor)
        ticket = state / "current-faq.ticket.json"
        prepared = run(
            BRIDGE,
            "prepare-launch",
            "--recycle-request",
            str(recycle),
            "--launch-request",
            str(launch),
            "--ticket",
            str(ticket),
        )
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        prepared_result = json.loads(prepared.stdout)["result"]
        self.assertTrue(prepared_result["prompt"].startswith(marker))
        receipted = run(
            BRIDGE,
            "record-launch-receipt",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "019fabce-d109-canonical",
            "--request-id",
            "current-faq-receipt",
            "--now",
            iso(minutes=1),
        )
        self.assertEqual(0, receipted.returncode, receipted.stderr)
        mirror = run(
            BRIDGE,
            "reconcile-external-task",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "019fabce-d77d-mirror",
            "--request-id",
            "current-faq-mirror",
            "--now",
            iso(minutes=2),
        )
        self.assertEqual(0, mirror.returncode, mirror.stderr)
        mirror_result = json.loads(mirror.stdout)["result"]
        self.assertEqual("DUPLICATE_STOP", mirror_result["classification"])
        self.assertFalse(mirror_result["mutation_allowed"])
        self.assertFalse(mirror_result["capacity_eligible"])
        self.assertEqual(0, mirror_result["zero_change_handback"]["changes"])
        progress = write_json(
            root / "mirror-progress.json",
            {
                "interface_version": "1.0",
                "request_id": "mirror-progress",
                "runtime_state": "active",
                "actual": {
                    "active_seconds": 601,
                    "queue_seconds": 0,
                    "setup_seconds": 1,
                    "tool_wait_seconds": 0,
                    "external_wait_seconds": 0,
                    "total_wall_seconds": 602,
                    "first_evidence_seconds": 10,
                    "safe_close_seconds": None,
                },
                "successor_request": None,
                "now": iso(minutes=2),
            },
        )
        mirror_reclassify = run(
            BRIDGE,
            "record-duration-progress",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "019fabce-d77d-mirror",
            "--request",
            str(progress),
        )
        self.assertEqual(3, mirror_reclassify.returncode)
        self.assertEqual(
            "EXTERNAL_MIRROR_STOP",
            json.loads(mirror_reclassify.stderr)["error"]["code"],
        )

        successor = launch_request(
            task_id="current-faq-successor",
            source_event_key="current-faq-successor-source",
            outcome_key="current-faq-successor-outcome",
            idempotency_key="current-faq-successor-idem",
            repo_root=str(repo),
            remote="https://github.com/pulkitsinghal/project-firestarter.git",
            now=iso(minutes=3),
            lease_expires_at=iso(minutes=33),
        )
        successor["target"]["base_sha"] = head
        successor["context"]["repo"] = (
            "github.com/pulkitsinghal/project-firestarter"
        )
        handback_value = handback_request(
            task_id="current-faq",
            handback_id="current-faq-close",
            now=iso(minutes=3),
        )
        handback_value["exact_refs"] = {
            "base_sha": head,
            "candidate_sha": head,
            "pr_url": "https://github.com/example-org/example-repo/pull/1",
            "merge_sha": head,
            "default_sha": head,
        }
        ticket_value = json.loads(ticket.read_text(encoding="utf-8"))
        handback_value["policy_snapshot_revision"] = ticket_value[
            "policy_snapshot_revision"
        ]
        handback_value["lease_epoch"] = ticket_value["lease_epoch"]
        handback_value["fencing_token"] = ticket_value["fencing_token"]
        handback_value["resources"].append(
            {
                "id": ticket_value["owner_claim_id"],
                "disposition": "removed",
                "reason": "canonical owner claim released by clean handback",
                "bytes": 0,
            }
        )
        handback = write_json(root / "handback.json", handback_value)
        refill = write_json(
            root / "refill.json",
            refill_request(
                candidates=[successor],
                request_id="current-faq-refill",
                status="interrupted/notLoaded",
                valid_clean_handback=True,
            ),
        )
        closed = run(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(ticket),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        close_result = json.loads(closed.stdout)["result"]
        self.assertEqual("SUCCESSOR_RESERVED", close_result["outcome"])
        successor_launch = close_result["launches"][0]
        successor_receipt = run(
            REFILL,
            "record-refill-receipt",
            "--saga-id",
            "current-faq-close",
            "--task-id",
            "current-faq-successor",
            "--external-thread-id",
            "current-successor-thread",
            "--request-id",
            "current-successor-receipt",
            "--now",
            iso(minutes=4),
        )
        self.assertEqual(
            0, successor_receipt.returncode, successor_receipt.stderr
        )
        self.assertTrue(successor_launch["prompt"])
        archived = run(
            BRIDGE,
            "record-archive-receipt",
            "--ticket",
            str(ticket),
            "--request-id",
            "current-faq-archive",
            "--now",
            iso(minutes=5),
        )
        self.assertEqual(0, archived.returncode, archived.stderr)
        status = run(BRIDGE, "status")
        self.assertEqual(0, status.returncode, status.stderr)
        status_result = json.loads(status.stdout)["result"]
        canonical = [
            item
            for item in status_result["tasks"]
            if item["capacity_eligible"]
        ]
        self.assertEqual(1, len(canonical))
        self.assertEqual(
            "current-successor-thread",
            canonical[0]["canonical_external_thread_id"],
        )
        durable = b"".join(
            path.read_bytes() for path in state.iterdir() if path.is_file()
        )
        self.assertNotIn(marker.encode(), durable)
        self.assertNotIn(
            hashlib.sha256(marker.encode()).hexdigest().encode(), durable
        )


if __name__ == "__main__":
    unittest.main()
