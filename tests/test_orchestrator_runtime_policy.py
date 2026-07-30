"""Checked-in root/spawn runtime policy and bootstrap verifier regressions."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = (
    ROOT
    / "addons"
    / "orchestrator_session"
    / "common"
    / "bin"
    / "verify-orchestrator-runtime.py"
)
PROJECT_CONFIG = ROOT / ".codex" / "config.toml"
ADDON_CONFIG = (
    ROOT / "addons" / "orchestrator_session" / "common" / ".codex" / "config.toml"
)


class OrchestratorRuntimePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = tempfile.TemporaryDirectory()
        self.root = Path(self.sandbox.name)
        self.project = self.root / "project"
        (self.project / ".codex").mkdir(parents=True)
        shutil.copyfile(PROJECT_CONFIG, self.project / ".codex" / "config.toml")
        self.user_config = self.root / "user-config.toml"
        self.attestation = self.root / "attestation.json"
        self.write_user_config(trusted=True)
        self.write_attestation()

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    def write_user_config(
        self,
        *,
        trusted: bool,
        user_model: str = "gpt-5.6-sol",
    ) -> None:
        trust = "trusted" if trusted else "untrusted"
        self.user_config.write_text(
            f'model = "{user_model}"\n'
            'model_reasoning_effort = "xhigh"\n'
            'service_tier = "fast"\n'
            "[features]\n"
            "fast_mode = true\n"
            "multi_agent = true\n"
            "[agents]\n"
            'default_subagent_model = "gpt-5.6-sol"\n'
            'default_subagent_reasoning_effort = "xhigh"\n'
            f'[projects."{self.project}"]\n'
            f'trust_level = "{trust}"\n',
            encoding="utf-8",
        )

    def write_attestation(
        self,
        *,
        model: str = "gpt-5.6-sol",
        effort: str = "xhigh",
        tier: str = "fast",
        fast_mode: bool = True,
        tier_source: str = "config-verified",
        tier_provenance: str = "trusted-project-and-user-config",
        auth_mode: str = "chatgpt",
    ) -> None:
        self.attestation.write_text(
            json.dumps(
                {
                    "model": model,
                    "model_reasoning_effort": effort,
                    "service_tier": tier,
                    "fast_mode": fast_mode,
                    "service_tier_attestation": tier_source,
                    "tier_provenance": tier_provenance,
                    "auth_mode": auth_mode,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def run_verifier(self, expected: int = 0) -> dict[str, object]:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(VERIFIER),
                "--project-root",
                str(self.project),
                "--user-config",
                str(self.user_config),
                "--runtime-attestation",
                str(self.attestation),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            expected,
            completed.returncode,
            f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        return json.loads(completed.stdout if expected == 0 else completed.stderr)

    def test_root_and_spawn_defaults_are_exact_and_config_verified(self) -> None:
        result = self.run_verifier()
        self.assertTrue(result["ok"])
        policy = result["policy"]
        self.assertEqual(
            {
                "model": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "service_tier": "fast",
                "fast_mode": True,
                "service_tier_attestation": "config-verified",
            },
            policy["root"],
        )
        self.assertEqual(
            {
                "model": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "service_tier": "fast",
                "fast_mode": True,
            },
            policy["worker_defaults"],
        )
        self.assertTrue(policy["multi_agent"])
        self.assertTrue(policy["root_excluded_from_worker_capacity"])
        self.assertTrue(result["precedence"]["service_tier_config_verified"])
        self.assertFalse(result["precedence"]["service_tier_runtime_attested"])
        self.assertEqual(PROJECT_CONFIG.read_bytes(), ADDON_CONFIG.read_bytes())

    def test_untrusted_project_fails_before_orchestration(self) -> None:
        self.write_user_config(trusted=False)
        result = self.run_verifier(expected=2)
        self.assertEqual("PROJECT_UNTRUSTED", result["error"]["code"])

    def test_project_spawn_default_drift_fails_closed(self) -> None:
        path = self.project / ".codex" / "config.toml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                'default_subagent_model = "gpt-5.6-sol"',
                'default_subagent_model = "gpt-5.6-terra"',
            ),
            encoding="utf-8",
        )
        result = self.run_verifier(expected=2)
        self.assertEqual("PROJECT_POLICY_DRIFT", result["error"]["code"])

    def test_cli_or_profile_runtime_override_drift_fails_closed(self) -> None:
        self.write_attestation(model="gpt-5.6-terra")
        result = self.run_verifier(expected=2)
        self.assertEqual("EFFECTIVE_RUNTIME_DRIFT", result["error"]["code"])

    def test_missing_tier_verification_is_truthfully_unattested(self) -> None:
        self.write_attestation(tier_source="unattested", tier_provenance="none")
        result = self.run_verifier(expected=2)
        self.assertEqual("SERVICE_TIER_UNATTESTED", result["error"]["code"])

    def test_conflicting_machine_default_fails_before_project_precedence(self) -> None:
        self.write_user_config(trusted=True, user_model="gpt-5.6-terra")
        result = self.run_verifier(expected=2)
        self.assertEqual("USER_POLICY_DRIFT", result["error"]["code"])

    def test_runtime_tier_provenance_is_accepted_when_platform_reports_it(
        self,
    ) -> None:
        self.write_attestation(
            tier_source="runtime", tier_provenance="platform-runtime"
        )
        result = self.run_verifier()
        self.assertTrue(result["precedence"]["service_tier_runtime_attested"])
        self.assertFalse(result["precedence"]["service_tier_config_verified"])

    def test_api_key_auth_cannot_claim_chatgpt_fast_semantics(self) -> None:
        self.write_attestation(auth_mode="api-key")
        result = self.run_verifier(expected=2)
        self.assertEqual("FAST_AUTH_MODE_UNSUPPORTED", result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
