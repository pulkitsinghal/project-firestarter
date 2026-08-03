from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = PLUGIN_ROOT / "scripts" / "desktop_host_adapter.py"
PRE_HOOK = PLUGIN_ROOT / "hooks" / "pre_tool_use_root_guard.py"
POST_HOOK = PLUGIN_ROOT / "hooks" / "post_tool_use_lifecycle.py"
SPEC = importlib.util.spec_from_file_location("desktop_host_adapter", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


def private(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = path.resolve(strict=True)
    os.chmod(path, 0o700)
    return path


def write_executable(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o700)
    return path


class DesktopHostAdapterTest(unittest.TestCase):
    def test_exact_root_is_guarded_worker_is_not_and_adapter_loss_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-attestation-") as raw:
            root = private(Path(raw))
            session_path = root / "session.json"
            socket_path = ADAPTER.short_socket_path(
                "synthetic-host", "direct-test-token"
            )
            host_session = {
                "adapter_sha256": ADAPTER.digest(ADAPTER_PATH),
                "approval_grant_enabled": True,
                "armed": True,
                "expires_at": "2099-01-01T00:00:00Z",
                "hook_bundle_sha256": ADAPTER.hook_bundle_digest(),
                "instance_id": "synthetic-host",
                "root_thread_id": "root-thread",
                "socket_path": str(socket_path),
            }
            ADAPTER.atomic_private_json(session_path, host_session)
            server = ADAPTER.AttestationServer(
                session_path,
                host_session,
            )
            server.start()
            try:
                root_result = self.invoke_hook(socket_path, "root-thread")
                worker_result = self.invoke_hook(socket_path, "worker-thread")
                root_control = self.invoke_hook(
                    socket_path,
                    "root-thread",
                    "mcp__pm_proxy_orchestrator__pm_proxy_doctor",
                )
                worker_control = self.invoke_hook(
                    socket_path,
                    "worker-thread",
                    "mcp__pm_proxy_orchestrator__pm_proxy_doctor",
                )
                worker_ungranted_control = self.invoke_hook(
                    socket_path,
                    "worker-thread",
                    "mcp__pm_proxy_orchestrator__pm_proxy_reconcile_expired_lease",
                )
                self.assertIn(
                    "ROOT_ORCHESTRATOR_TASK_DOMAIN_DENIED:Bash",
                    root_result.stdout,
                )
                self.assertEqual("", worker_result.stdout)
                self.assertEqual("", root_control.stdout)
                self.assertIn(
                    "WORKER_ORCHESTRATOR_CONTROL_DENIED",
                    worker_control.stdout,
                )
                self.assertEqual("", worker_ungranted_control.stdout)
                for control_name in ADAPTER.PROMPT_FREE_CONTROL_TOOLS:
                    with self.subTest(control_name=control_name):
                        full_name = (
                            "mcp__pm_proxy_orchestrator__" + control_name
                        )
                        self.assertEqual(
                            "",
                            self.invoke_hook(
                                socket_path,
                                "root-thread",
                                full_name,
                            ).stdout,
                        )
                        self.assertIn(
                            "WORKER_ORCHESTRATOR_CONTROL_DENIED",
                            self.invoke_hook(
                                socket_path,
                                "worker-thread",
                                full_name,
                            ).stdout,
                        )
                tampered_grant = dict(host_session)
                tampered_grant["approval_grant_enabled"] = False
                ADAPTER.atomic_private_json(session_path, tampered_grant)
                grant_drift = self.invoke_hook(
                    socket_path,
                    "root-thread",
                    "mcp__pm_proxy_orchestrator__pm_proxy_doctor",
                )
                self.assertIn("ROOT_HOST_ATTESTATION_INVALID", grant_drift.stdout)
                tampered = dict(host_session)
                tampered["root_thread_id"] = "different-root"
                ADAPTER.atomic_private_json(session_path, tampered)
                tampered_root = self.invoke_hook(socket_path, "root-thread")
                self.assertIn("ROOT_HOST_ATTESTATION_INVALID", tampered_root.stdout)
                disarmed = dict(host_session)
                disarmed["armed"] = False
                ADAPTER.atomic_private_json(
                    session_path,
                    disarmed,
                )
                disarmed_root = self.invoke_hook(socket_path, "root-thread")
                disarmed_worker = self.invoke_hook(socket_path, "worker-thread")
                self.assertIn("ROOT_HOST_ATTESTATION_INVALID", disarmed_root.stdout)
                self.assertIn("ROOT_HOST_ATTESTATION_INVALID", disarmed_worker.stdout)
            finally:
                server.stop()
            bootstrap_session = dict(host_session)
            bootstrap_session["approval_grant_enabled"] = False
            ADAPTER.atomic_private_json(session_path, bootstrap_session)
            bootstrap_server = ADAPTER.AttestationServer(
                session_path,
                bootstrap_session,
            )
            bootstrap_server.start()
            try:
                bootstrap_worker = self.invoke_hook(
                    socket_path,
                    "worker-thread",
                    "mcp__pm_proxy_orchestrator__pm_proxy_doctor",
                )
                self.assertEqual("", bootstrap_worker.stdout)
            finally:
                bootstrap_server.stop()
            unavailable = self.invoke_hook(socket_path, "worker-thread")
            self.assertIn("ROOT_HOST_ATTESTATION_UNAVAILABLE", unavailable.stdout)

    @staticmethod
    def invoke_hook(
        socket_path: Path,
        session_id: str,
        tool_name: str = "Bash",
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment.pop("ROOT_ORCHESTRATOR_ROLE", None)
        environment[ADAPTER.SOCKET_ENV] = str(socket_path)
        return subprocess.run(
            [sys.executable, str(PRE_HOOK)],
            input=json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "tool_input": {"command": "/usr/bin/true"},
                    "tool_use_id": f"call-{session_id}",
                }
            ),
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
            env=environment,
        )

    def test_proxy_preserves_protocol_and_removes_host_secret_from_real_app_server(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-proxy-") as raw:
            home = private(Path(raw))
            private(home / ".codex" / "orchestrator-state")
            instance = private(home / "instance")
            record = instance / "record.json"
            fake = write_executable(
                instance / "fake-codex",
                """#!/usr/bin/env python3
import json
import os
import subprocess
import sys

def hook(session_id, tool_name="Bash"):
    event = {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": {"command": "/usr/bin/true"},
        "tool_use_id": "call-" + session_id,
    }
    return subprocess.run(
        [sys.executable, os.environ["PRE_HOOK_PATH"]],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
        env=os.environ,
    ).stdout

record = {
    "args": sys.argv[1:],
    "root": hook("root-thread"),
    "worker": hook("worker-thread"),
    "root_control": hook("root-thread", "mcp__pm_proxy_orchestrator__pm_proxy_doctor"),
    "worker_control": hook("worker-thread", "mcp__pm_proxy_orchestrator__pm_proxy_doctor"),
    "worker_ungranted_control": hook(
        "worker-thread",
        "mcp__pm_proxy_orchestrator__pm_proxy_reconcile_expired_lease",
    ),
    "root_role_present": "ROOT_ORCHESTRATOR_ROLE" in os.environ,
    "socket_present": "ORC_DESKTOP_HOST_SOCKET" in os.environ,
    "token_present": "ORC_DESKTOP_HOST_TOKEN" in os.environ,
    "session_present": "ORC_DESKTOP_HOST_SESSION" in os.environ,
}
with open(os.environ["FAKE_RECORD"], "w", encoding="utf-8") as handle:
    json.dump(record, handle, sort_keys=True)
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
""",
            )
            token = "synthetic-private-token"
            session_path = instance / "session.json"
            now = ADAPTER.utc_now()
            session = self.full_session(
                instance=instance,
                fake_codex=fake,
                token=token,
                now=now,
            )
            ADAPTER.atomic_private_json(session_path, session)
            environment = dict(os.environ)
            environment.update(
                {
                    "HOME": str(home),
                    "FAKE_RECORD": str(record),
                    "PRE_HOOK_PATH": str(PRE_HOOK),
                    ADAPTER.SESSION_ENV: str(session_path),
                    ADAPTER.TOKEN_ENV: token,
                    ADAPTER.REAL_CODEX_ENV: str(fake),
                }
            )
            message = '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ADAPTER_PATH),
                    "-c",
                    "features.code_mode_host=true",
                    "app-server",
                    "--analytics-default-enabled",
                ],
                input=message,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
                env=environment,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(message, completed.stdout)
            observed = json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual(
                [
                    "-c",
                    "features.code_mode_host=true",
                    *ADAPTER.approval_grant_arguments(),
                    "app-server",
                    "--analytics-default-enabled",
                ],
                observed["args"],
            )
            self.assertIn(ADAPTER.DENIAL_MARKER, observed["root"])
            self.assertEqual("", observed["worker"])
            self.assertEqual("", observed["root_control"])
            self.assertIn(
                "WORKER_ORCHESTRATOR_CONTROL_DENIED",
                observed["worker_control"],
            )
            self.assertEqual("", observed["worker_ungranted_control"])
            self.assertFalse(observed["root_role_present"])
            self.assertTrue(observed["socket_present"])
            self.assertFalse(observed["token_present"])
            self.assertFalse(observed["session_present"])

    def test_post_hook_records_lifecycle_only_for_exact_root(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-post-") as raw:
            home = private(Path(raw))
            state_root = private(home / ".codex" / "orchestrator-state")
            instance = private(home / "instance")
            session_path = instance / "session.json"
            socket_path = ADAPTER.short_socket_path(
                "synthetic-post", "post-test-token"
            )
            host_session = {
                "adapter_sha256": ADAPTER.digest(ADAPTER_PATH),
                "approval_grant_enabled": True,
                "armed": True,
                "expires_at": "2099-01-01T00:00:00Z",
                "hook_bundle_sha256": ADAPTER.hook_bundle_digest(),
                "instance_id": "synthetic-post",
                "root_thread_id": "root-thread",
                "socket_path": str(socket_path),
            }
            ADAPTER.atomic_private_json(session_path, host_session)
            server = ADAPTER.AttestationServer(
                session_path,
                host_session,
            )
            server.start()
            try:
                for session_id, worker_id in (
                    ("root-thread", "observed-by-root"),
                    ("worker-thread", "observed-by-worker"),
                ):
                    environment = dict(os.environ)
                    environment.pop("ROOT_ORCHESTRATOR_ROLE", None)
                    environment["HOME"] = str(home)
                    environment[ADAPTER.SOCKET_ENV] = str(socket_path)
                    completed = subprocess.run(
                        [sys.executable, str(POST_HOOK)],
                        input=json.dumps(
                            {
                                "hook_event_name": "PostToolUse",
                                "session_id": session_id,
                                "tool_name": "codex_appread_thread",
                                "tool_input": {"threadId": worker_id},
                                "tool_response": {"status": "completed"},
                            }
                        ),
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=5,
                        env=environment,
                    )
                    self.assertEqual(0, completed.returncode, completed.stderr)
            finally:
                server.stop()
            ledger = json.loads(
                (state_root / ".dispatcher-lifecycle.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual({"root-thread": ["observed-by-root"]}, ledger)

    @staticmethod
    def full_session(
        *, instance: Path, fake_codex: Path, token: str, now: dt.datetime
    ) -> dict[str, object]:
        electron_data = private(instance / "electron-data")
        proof = instance / "live-proof.json"
        proof.write_text(
            json.dumps(
                {
                    "dispatcher_adoption_sha256": "1" * 64,
                    "plugin_version": ADAPTER.manifest()["version"],
                    "prompt_free_control_grant_verified": True,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(proof, 0o600)
        return {
            "adapter_sha256": ADAPTER.digest(ADAPTER_PATH),
            "approval_grant_enabled": True,
            "approval_grant_sha256": ADAPTER.approval_grant_digest(),
            "app_server_pid": None,
            "armed": True,
            "codex_cli": str(fake_codex),
            "codex_cli_sha256": ADAPTER.digest(fake_codex),
            "created_at": ADAPTER.iso(now),
            "desktop_executable": str(fake_codex),
            "desktop_executable_sha256": ADAPTER.digest(fake_codex),
            "desktop_isolation_argument": f"--user-data-dir={electron_data}",
            "desktop_pid": None,
            "dispatcher_adoption_sha256": "1" * 64,
            "electron_data_dir": str(electron_data),
            "expires_at": ADAPTER.iso(now + dt.timedelta(minutes=10)),
            "hook_bundle_sha256": ADAPTER.hook_bundle_digest(),
            "instance_id": "synthetic-host",
            "plugin_version": ADAPTER.manifest()["version"],
            "proof_sha256": ADAPTER.digest(proof),
            "proxy_pid": None,
            "root_thread_id": "root-thread",
            "session_version": ADAPTER.SESSION_VERSION,
            "socket_path": str(
                ADAPTER.short_socket_path("synthetic-host", token)
            ),
            "state_dir": str(instance),
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def verified_pin() -> dict[str, str]:
        return {
            "runtime_sha256": "1" * 64,
            "dispatcher_adoption_sha256": "2" * 64,
            "prompt_free_control_grant_verified": True,
        }

    def test_prompt_free_grant_is_exact_per_tool_and_precedes_app_server(self):
        expected = {
            "pm_proxy_close_and_refill",
            "pm_proxy_configure_capacity",
            "pm_proxy_doctor",
            "pm_proxy_heartbeat",
            "pm_proxy_lifecycle_watchdog",
            "pm_proxy_prepare_launch",
            "pm_proxy_record_archive_receipt",
            "pm_proxy_record_launch_receipt",
            "pm_proxy_record_refill_receipt",
            "pm_proxy_slot_status",
            "pm_proxy_status",
            "pm_proxy_verify_runtime",
            "pm_proxy_watchdog_refill",
        }
        self.assertEqual(expected, set(ADAPTER.PROMPT_FREE_CONTROL_TOOLS))
        self.assertNotIn(
            "pm_proxy_reconcile_expired_lease",
            ADAPTER.PROMPT_FREE_CONTROL_TOOLS,
        )
        grant = ADAPTER.approval_grant_arguments()
        self.assertEqual(2 * len(expected), len(grant))
        self.assertEqual(["-c"] * len(expected), grant[::2])
        for tool, setting in zip(ADAPTER.PROMPT_FREE_CONTROL_TOOLS, grant[1::2]):
            self.assertIn(f'tools."{tool}"', setting)
            self.assertTrue(setting.endswith('approval_mode="approve"'))
            self.assertNotIn("Bash", setting)
            self.assertNotIn("filesystem", setting)
            self.assertNotIn("browser", setting)
            self.assertNotIn("sites", setting.lower())

        hostile_default = (
            'plugins."pm-proxy-orchestrator@project-firestarter".'
            'mcp_servers."pm-proxy-orchestrator".tools."pm_proxy_doctor".'
            'approval_mode="prompt"'
        )
        original = ["-c", hostile_default, "app-server", "--analytics-default-enabled"]
        self.assertEqual(
            original,
            ADAPTER.isolated_app_server_arguments(
                original,
                grant_enabled=False,
            ),
        )
        isolated = ADAPTER.isolated_app_server_arguments(original)
        app_server_index = isolated.index("app-server")
        self.assertEqual(original[:2], isolated[:2])
        self.assertEqual(
            ADAPTER.approval_grant_arguments(),
            isolated[2:app_server_index],
        )
        self.assertEqual(original[2:], isolated[app_server_index:])

    def test_mcp_doctor_enables_grant_only_for_exact_current_covered_adoption(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-adoption-doctor-") as raw:
            state = private(Path(raw))
            version = ADAPTER.manifest()["version"]

            def completed(*, adoption_version: str, proof_value: bool = True):
                proofs = {
                    key: proof_value for key in ADAPTER.ADOPTION_REQUIRED_TRUE
                }
                proofs["universal_coverage_claimed"] = False
                adoption = {
                    "request_id": "adoption-current",
                    "adoption_mode": "COVERED_PATH_GUARDRAIL",
                    "plugin_version": adoption_version,
                    "recorded_at": "2026-08-03T00:00:00Z",
                    "proofs": proofs,
                    "covered_path_dispatcher_enforcement": True,
                    "universal_dispatcher_enforcement": False,
                }
                safety = {
                    "runtime_pin_verified": True,
                    "dispatcher_adoption_version_matches": True,
                    "covered_path_dispatcher_enforcement": True,
                    "platform_dispatcher_enforcement": False,
                    "automatic_launch_refill_allowed": True,
                    "covered_path_automatic_launch_refill_allowed": True,
                    "unattended_automatic_launch_refill_allowed": False,
                    "automatic_launch_refill_scope": "COVERED_PATH_ONLY",
                    "universal_dispatcher_enforcement": False,
                }
                responses = [
                    {
                        "jsonrpc": "2.0",
                        "id": "initialize",
                        "result": {"serverInfo": {"version": version}},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": "list",
                        "result": {
                            "tools": [
                                {"name": name} for name in ADAPTER.REQUIRED_TOOLS
                            ]
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": "doctor",
                        "result": {
                            "structuredContent": {
                                "ok": True,
                                "result": {
                                    "runtime_pin": {
                                        "verified": True,
                                        "runtime_sha256": "a" * 64,
                                    }
                                },
                            }
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": "status",
                        "result": {
                            "structuredContent": {
                                "ok": True,
                                "result": {
                                    "lifecycle_watchdog": {
                                        "dispatcher_adoption": adoption,
                                    },
                                    "operational_safety": safety,
                                },
                            }
                        },
                    },
                ]
                return subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="".join(
                        json.dumps(item, separators=(",", ":")) + "\n"
                        for item in responses
                    ),
                    stderr="",
                )

            with mock.patch.object(
                ADAPTER.subprocess,
                "run",
                return_value=completed(adoption_version=version),
            ):
                observed_version, pin = ADAPTER.mcp_doctor(state)
            self.assertEqual(version, observed_version)
            self.assertTrue(pin["prompt_free_control_grant_verified"])
            self.assertRegex(pin["dispatcher_adoption_sha256"], r"^[0-9a-f]{64}$")

            for response in (
                completed(adoption_version="0.3.4"),
                completed(adoption_version=version, proof_value=False),
            ):
                with mock.patch.object(
                    ADAPTER.subprocess,
                    "run",
                    return_value=response,
                ):
                    _, unverified = ADAPTER.mcp_doctor(state)
                self.assertFalse(unverified["prompt_free_control_grant_verified"])
                self.assertIsNone(unverified["dispatcher_adoption_sha256"])

    def test_proxy_rejects_non_app_server_invocation_before_real_cli(self):
        completed = subprocess.run(
            [sys.executable, str(ADAPTER_PATH), "exec", "synthetic"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("only-foreground-app-server-is-allowed", completed.stderr)

    def test_mac_single_instance_fixture_reproduces_environment_only_redirect(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-mac-redirect-") as raw:
            root = private(Path(raw))
            desktop = root / "ChatGPT.app" / "Contents" / "MacOS" / "ChatGPT"
            electron_data = private(root / "isolated-electron-data")
            normal_data = root / "normal-desktop-data"
            capability = "synthetic-private-capability"
            environment = {
                "CODEX_ELECTRON_USER_DATA_PATH": str(electron_data),
                ADAPTER.TOKEN_ENV: capability,
            }

            def mac_single_instance_target(command: list[str]) -> Path:
                switches = [
                    value.removeprefix(ADAPTER.USER_DATA_SWITCH)
                    for value in command[1:]
                    if value.startswith(ADAPTER.USER_DATA_SWITCH)
                ]
                return Path(switches[0]) if len(switches) == 1 else normal_data

            legacy_environment_only = [str(desktop)]
            supported = ADAPTER.desktop_launch_command(desktop, electron_data)
            self.assertEqual(normal_data, mac_single_instance_target(legacy_environment_only))
            self.assertEqual(electron_data, mac_single_instance_target(supported))
            self.assertEqual(str(electron_data), environment["CODEX_ELECTRON_USER_DATA_PATH"])
            self.assertNotIn(capability, supported)

    def test_launch_uses_isolated_data_and_never_exports_root_role_to_desktop(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-launch-") as raw:
            root = private(Path(raw))
            instance = private(root / "instance")
            state = private(root / "state")
            codex = write_executable(root / "codex", "#!/bin/sh\nexit 0\n")
            desktop = write_executable(root / "desktop", "#!/bin/sh\nexit 0\n")
            proof = instance / "live-proof.json"
            proof.write_text("{}\n", encoding="utf-8")
            os.chmod(proof, 0o600)
            version = ADAPTER.manifest()["version"]
            args = argparse.Namespace(
                instance_id="synthetic-host",
                instance_dir=str(instance),
                root_thread_id="root-thread",
                state_dir=str(state),
                codex_cli=str(codex),
                desktop_executable=str(desktop),
                project=None,
            )

            class FakeProcess:
                pid = 4242

                @staticmethod
                def poll():
                    return None

            captured: dict[str, object] = {}

            def fake_popen(command, **kwargs):
                captured["command"] = command
                captured.update(kwargs)
                return FakeProcess()

            with (
                mock.patch.object(ADAPTER, "probe_hook"),
                mock.patch.object(ADAPTER, "installed_plugin"),
                mock.patch.object(
                    ADAPTER,
                    "mcp_doctor",
                    return_value=(version, self.verified_pin()),
                ),
                mock.patch.object(ADAPTER, "validate_proof", return_value={}),
                mock.patch.object(ADAPTER.subprocess, "Popen", side_effect=fake_popen),
                mock.patch.object(ADAPTER.time, "sleep"),
                mock.patch.object(ADAPTER, "wait_for_proxy", return_value=True),
                mock.patch.dict(os.environ, {"ROOT_ORCHESTRATOR_ROLE": ""}),
            ):
                result = ADAPTER.launch(args)
            self.assertTrue(result["ok"])
            environment = captured["env"]
            self.assertNotIn("ROOT_ORCHESTRATOR_ROLE", environment)
            self.assertEqual(str(ADAPTER_PATH), environment["CODEX_CLI_PATH"])
            self.assertEqual("1", environment["CODEX_APP_SERVER_FORCE_CLI"])
            self.assertTrue(
                environment["CODEX_ELECTRON_USER_DATA_PATH"].startswith(str(instance))
            )
            self.assertEqual(
                [
                    str(desktop),
                    f"--user-data-dir={instance / 'electron-data'}",
                ],
                captured["command"],
            )
            serialized_command = "\0".join(captured["command"])
            self.assertNotIn(environment[ADAPTER.TOKEN_ENV], serialized_command)
            self.assertNotIn(environment[ADAPTER.SESSION_ENV], serialized_command)
            session = ADAPTER.read_private_json(instance / "session.json")
            self.assertEqual("root-thread", session["root_thread_id"])
            self.assertTrue(session["armed"])
            self.assertEqual(
                f"--user-data-dir={instance / 'electron-data'}",
                session["desktop_isolation_argument"],
            )

    def test_launch_disarms_and_terminates_only_isolated_desktop_if_proxy_is_absent(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-startup-failure-") as raw:
            root = private(Path(raw))
            instance = private(root / "instance")
            state = private(root / "state")
            codex = write_executable(root / "codex", "#!/bin/sh\nexit 0\n")
            desktop = write_executable(root / "desktop", "#!/bin/sh\nexit 0\n")
            proof = instance / "live-proof.json"
            proof.write_text("{}\n", encoding="utf-8")
            os.chmod(proof, 0o600)
            version = ADAPTER.manifest()["version"]
            args = argparse.Namespace(
                instance_id="synthetic-host",
                instance_dir=str(instance),
                root_thread_id="root-thread",
                state_dir=str(state),
                codex_cli=str(codex),
                desktop_executable=str(desktop),
                project=None,
            )

            class FakeProcess:
                pid = 4242
                terminated = False

                @staticmethod
                def poll():
                    return None

                @classmethod
                def terminate(cls):
                    cls.terminated = True

            with (
                mock.patch.object(ADAPTER, "probe_hook"),
                mock.patch.object(ADAPTER, "installed_plugin"),
                mock.patch.object(
                    ADAPTER,
                    "mcp_doctor",
                    return_value=(version, self.verified_pin()),
                ),
                mock.patch.object(ADAPTER, "validate_proof", return_value={}),
                mock.patch.object(
                    ADAPTER.subprocess, "Popen", return_value=FakeProcess()
                ),
                mock.patch.object(ADAPTER.time, "sleep"),
                mock.patch.object(ADAPTER, "wait_for_proxy", return_value=False),
                mock.patch.dict(os.environ, {"ROOT_ORCHESTRATOR_ROLE": ""}),
            ):
                with self.assertRaisesRegex(
                    ADAPTER.AdapterError, "desktop-host-proxy-not-observed"
                ):
                    ADAPTER.launch(args)
            session = ADAPTER.read_private_json(instance / "session.json")
            self.assertFalse(session["armed"])
            self.assertTrue(FakeProcess.terminated)

    def test_wait_for_proxy_fails_closed_without_exact_desktop_isolation(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-isolation-loss-") as raw:
            root = private(Path(raw))
            fake = write_executable(root / "fake-codex", "#!/bin/sh\nexit 0\n")
            session = self.full_session(
                instance=root,
                fake_codex=fake,
                token="isolation-loss-token",
                now=ADAPTER.utc_now(),
            )
            session.update(
                {"desktop_pid": 4201, "proxy_pid": 4202, "app_server_pid": 4203}
            )
            ADAPTER.atomic_private_json(root / "session.json", session)
            commands = {
                4201: str(fake),
                4202: f"{ADAPTER_PATH} app-server",
                4203: f"{fake} app-server",
            }
            with mock.patch.object(
                ADAPTER, "process_command", side_effect=lambda pid: commands.get(pid)
            ):
                self.assertFalse(ADAPTER.wait_for_proxy(root / "session.json", timeout=0.2))

    def test_exact_process_observation_integration(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-process-e2e-") as raw:
            root = private(Path(raw))
            token = "process-observation-token"
            sleeper = "trap 'exit 0' TERM INT; while :; do sleep 1 & wait; done"
            process_executable = Path("/bin/sh").resolve(strict=True)
            session = self.full_session(
                instance=root,
                fake_codex=process_executable,
                token=token,
                now=ADAPTER.utc_now(),
            )
            processes = [
                subprocess.Popen(
                    [
                        str(process_executable),
                        "-c",
                        sleeper,
                        str(session["desktop_isolation_argument"]),
                    ]
                ),
                subprocess.Popen(
                    [
                        str(process_executable),
                        "-c",
                        sleeper,
                        str(ADAPTER_PATH),
                        "app-server",
                    ]
                ),
                subprocess.Popen(
                    [str(process_executable), "-c", sleeper, "app-server"]
                ),
            ]
            try:
                session.update(
                    {
                        "desktop_executable": str(process_executable),
                        "desktop_executable_sha256": ADAPTER.digest(process_executable),
                        "desktop_pid": processes[0].pid,
                        "proxy_pid": processes[1].pid,
                        "app_server_pid": processes[2].pid,
                    }
                )
                ADAPTER.atomic_private_json(root / "session.json", session)
                self.assertTrue(
                    ADAPTER.wait_for_proxy(root / "session.json", timeout=2.0)
                )
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                for process in processes:
                    process.wait(timeout=5)

    def test_launch_disarms_if_isolated_desktop_cannot_start(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-spawn-failure-") as raw:
            root = private(Path(raw))
            instance = private(root / "instance")
            state = private(root / "state")
            codex = write_executable(root / "codex", "#!/bin/sh\nexit 0\n")
            desktop = write_executable(root / "desktop", "#!/bin/sh\nexit 0\n")
            proof = instance / "live-proof.json"
            proof.write_text("{}\n", encoding="utf-8")
            os.chmod(proof, 0o600)
            version = ADAPTER.manifest()["version"]
            args = argparse.Namespace(
                instance_id="synthetic-host",
                instance_dir=str(instance),
                root_thread_id="root-thread",
                state_dir=str(state),
                codex_cli=str(codex),
                desktop_executable=str(desktop),
                project=None,
            )
            with (
                mock.patch.object(ADAPTER, "probe_hook"),
                mock.patch.object(ADAPTER, "installed_plugin"),
                mock.patch.object(
                    ADAPTER,
                    "mcp_doctor",
                    return_value=(version, self.verified_pin()),
                ),
                mock.patch.object(ADAPTER, "validate_proof", return_value={}),
                mock.patch.object(
                    ADAPTER.subprocess,
                    "Popen",
                    side_effect=OSError("synthetic desktop start failure"),
                ),
                mock.patch.dict(os.environ, {"ROOT_ORCHESTRATOR_ROLE": ""}),
            ):
                with self.assertRaisesRegex(
                    ADAPTER.AdapterError, "desktop-host-start-failed"
                ):
                    ADAPTER.launch(args)
            self.assertFalse(
                ADAPTER.read_private_json(instance / "session.json")["armed"]
            )

    def test_launch_disarms_before_spawn_if_private_log_is_invalid(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-log-failure-") as raw:
            root = private(Path(raw))
            instance = private(root / "instance")
            state = private(root / "state")
            codex = write_executable(root / "codex", "#!/bin/sh\nexit 0\n")
            desktop = write_executable(root / "desktop", "#!/bin/sh\nexit 0\n")
            private(instance / "desktop.log")
            proof = instance / "live-proof.json"
            proof.write_text("{}\n", encoding="utf-8")
            os.chmod(proof, 0o600)
            version = ADAPTER.manifest()["version"]
            args = argparse.Namespace(
                instance_id="synthetic-host",
                instance_dir=str(instance),
                root_thread_id="root-thread",
                state_dir=str(state),
                codex_cli=str(codex),
                desktop_executable=str(desktop),
                project=None,
            )
            with (
                mock.patch.object(ADAPTER, "probe_hook"),
                mock.patch.object(ADAPTER, "installed_plugin"),
                mock.patch.object(
                    ADAPTER,
                    "mcp_doctor",
                    return_value=(version, self.verified_pin()),
                ),
                mock.patch.object(ADAPTER, "validate_proof", return_value={}),
                mock.patch.object(ADAPTER.subprocess, "Popen") as popen,
                mock.patch.dict(os.environ, {"ROOT_ORCHESTRATOR_ROLE": ""}),
            ):
                with self.assertRaisesRegex(ADAPTER.AdapterError, "desktop-log-invalid"):
                    ADAPTER.launch(args)
            popen.assert_not_called()
            self.assertFalse(
                ADAPTER.read_private_json(instance / "session.json")["armed"]
            )

    def test_proxy_refuses_wrong_capability_token_before_starting_real_cli(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-token-") as raw:
            root = private(Path(raw))
            fake = write_executable(root / "fake-codex", "#!/bin/sh\nexit 0\n")
            token = "correct-token"
            session_path = root / "session.json"
            ADAPTER.atomic_private_json(
                session_path,
                self.full_session(
                    instance=root,
                    fake_codex=fake,
                    token=token,
                    now=ADAPTER.utc_now(),
                ),
            )
            with mock.patch.dict(
                os.environ,
                {
                    ADAPTER.SESSION_ENV: str(session_path),
                    ADAPTER.TOKEN_ENV: "wrong-token",
                    ADAPTER.REAL_CODEX_ENV: str(fake),
                },
            ):
                with self.assertRaisesRegex(ADAPTER.AdapterError, "host-session-invalid"):
                    ADAPTER.validate_session_from_environment()

    def test_proxy_rejects_tampered_desktop_isolation_before_real_cli(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-isolation-tamper-") as raw:
            root = private(Path(raw))
            fake = write_executable(root / "fake-codex", "#!/bin/sh\nexit 0\n")
            token = "correct-token"
            session_path = root / "session.json"
            session = self.full_session(
                instance=root,
                fake_codex=fake,
                token=token,
                now=ADAPTER.utc_now(),
            )
            session["desktop_isolation_argument"] += "-redirected"
            ADAPTER.atomic_private_json(session_path, session)
            with mock.patch.dict(
                os.environ,
                {
                    ADAPTER.SESSION_ENV: str(session_path),
                    ADAPTER.TOKEN_ENV: token,
                    ADAPTER.REAL_CODEX_ENV: str(fake),
                },
            ):
                with self.assertRaisesRegex(ADAPTER.AdapterError, "host-session-invalid"):
                    ADAPTER.validate_session_from_environment()

    def test_proxy_rejects_tampered_or_missing_prompt_free_grant_binding(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-grant-tamper-") as raw:
            root = private(Path(raw))
            fake = write_executable(root / "fake-codex", "#!/bin/sh\nexit 0\n")
            token = "correct-token"
            session_path = root / "session.json"
            session = self.full_session(
                instance=root,
                fake_codex=fake,
                token=token,
                now=ADAPTER.utc_now(),
            )
            session["approval_grant_sha256"] = "0" * 64
            ADAPTER.atomic_private_json(session_path, session)
            environment = {
                ADAPTER.SESSION_ENV: str(session_path),
                ADAPTER.TOKEN_ENV: token,
                ADAPTER.REAL_CODEX_ENV: str(fake),
            }
            with mock.patch.dict(os.environ, environment):
                with self.assertRaisesRegex(ADAPTER.AdapterError, "host-session-invalid"):
                    ADAPTER.validate_session_from_environment()

            session = self.full_session(
                instance=root,
                fake_codex=fake,
                token=token,
                now=ADAPTER.utc_now(),
            )
            session.pop("dispatcher_adoption_sha256")
            ADAPTER.atomic_private_json(session_path, session)
            with mock.patch.dict(os.environ, environment):
                with self.assertRaisesRegex(ADAPTER.AdapterError, "fields-invalid"):
                    ADAPTER.validate_session_from_environment()

    def test_proxy_cleans_attestation_socket_if_real_app_server_cannot_start(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-child-failure-") as raw:
            root = private(Path(raw))
            fake = write_executable(root / "fake-codex", "#!/bin/sh\nexit 0\n")
            token = "correct-token"
            session_path = root / "session.json"
            session = self.full_session(
                instance=root,
                fake_codex=fake,
                token=token,
                now=ADAPTER.utc_now(),
            )
            socket_path = Path(str(session["socket_path"]))
            ADAPTER.atomic_private_json(session_path, session)
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        ADAPTER.SESSION_ENV: str(session_path),
                        ADAPTER.TOKEN_ENV: token,
                        ADAPTER.REAL_CODEX_ENV: str(fake),
                    },
                ),
                mock.patch.object(
                    ADAPTER.subprocess,
                    "Popen",
                    side_effect=OSError("synthetic start failure"),
                ),
            ):
                with self.assertRaisesRegex(
                    ADAPTER.AdapterError, "real-app-server-start-failed"
                ):
                    ADAPTER.run_proxy(["app-server"])
            self.assertFalse(socket_path.exists())

    def test_launch_refuses_inherited_global_root_role_before_any_side_effect(self):
        args = argparse.Namespace(
            instance_id="synthetic-host",
            instance_dir="/synthetic/unused",
            root_thread_id="root-thread",
            state_dir="/synthetic/unused",
            codex_cli="/synthetic/unused",
            desktop_executable="/synthetic/unused",
            project=None,
        )
        with mock.patch.dict(
            os.environ,
            {"ROOT_ORCHESTRATOR_ROLE": "trusted-project-hook"},
        ):
            with self.assertRaisesRegex(
                ADAPTER.AdapterError, "global-root-role-must-be-unset"
            ):
                ADAPTER.launch(args)

    def test_launch_refuses_inherited_private_host_capability(self):
        args = argparse.Namespace(
            instance_id="synthetic-host",
            instance_dir="/synthetic/unused",
            root_thread_id="root-thread",
            state_dir="/synthetic/unused",
            codex_cli="/synthetic/unused",
            desktop_executable="/synthetic/unused",
            project=None,
        )
        with mock.patch.dict(
            os.environ,
            {
                "ROOT_ORCHESTRATOR_ROLE": "",
                ADAPTER.TOKEN_ENV: "must-not-be-inherited",
            },
        ):
            with self.assertRaisesRegex(
                ADAPTER.AdapterError, "host-adapter-environment-must-be-unset"
            ):
                ADAPTER.launch(args)

    def test_installed_plugin_version_mismatch_fails_before_host_launch(self):
        response = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "installed": [
                        {
                            "pluginId": "pm-proxy-orchestrator@project-firestarter",
                            "installed": True,
                            "enabled": True,
                            "version": "0.3.3",
                        }
                    ]
                }
            ),
            stderr="",
        )
        with mock.patch.object(ADAPTER.subprocess, "run", return_value=response):
            with self.assertRaisesRegex(
                ADAPTER.AdapterError, "installed-plugin-version-mismatch"
            ):
                ADAPTER.installed_plugin(Path("/synthetic/codex"), "0.3.4")

    def test_installed_plugin_must_resolve_to_exact_adapter_source(self):
        response = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "installed": [
                        {
                            "pluginId": "pm-proxy-orchestrator@project-firestarter",
                            "installed": True,
                            "enabled": True,
                            "version": ADAPTER.manifest()["version"],
                            "source": {
                                "source": "local",
                                "path": "/synthetic/wrong-source",
                            },
                        }
                    ]
                }
            ),
            stderr="",
        )
        with mock.patch.object(ADAPTER.subprocess, "run", return_value=response):
            with self.assertRaisesRegex(
                ADAPTER.AdapterError, "installed-plugin-version-mismatch"
            ):
                ADAPTER.installed_plugin(
                    Path("/synthetic/codex"), ADAPTER.manifest()["version"]
                )

    def test_installed_plugin_rejects_source_cache_content_drift(self):
        version = ADAPTER.manifest()["version"]
        response = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "installed": [
                        {
                            "pluginId": "pm-proxy-orchestrator@project-firestarter",
                            "installed": True,
                            "enabled": True,
                            "version": version,
                            "source": {
                                "source": "local",
                                "path": str(PLUGIN_ROOT),
                            },
                        }
                    ]
                }
            ),
            stderr="",
        )
        with (
            mock.patch.object(ADAPTER.subprocess, "run", return_value=response),
            mock.patch.object(
                ADAPTER, "secure_plugin_dir", side_effect=lambda path: path
            ),
            mock.patch.object(
                ADAPTER, "plugin_tree_digest", side_effect=["source", "cache"]
            ),
        ):
            with self.assertRaisesRegex(
                ADAPTER.AdapterError, "installed-plugin-cache-mismatch"
            ):
                ADAPTER.installed_plugin(Path("/synthetic/codex"), version)

    def test_installed_plugin_accepts_exact_source_cache_match(self):
        version = ADAPTER.manifest()["version"]
        response = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "installed": [
                        {
                            "pluginId": "pm-proxy-orchestrator@project-firestarter",
                            "installed": True,
                            "enabled": True,
                            "version": version,
                            "source": {
                                "source": "local",
                                "path": str(PLUGIN_ROOT),
                            },
                        }
                    ]
                }
            ),
            stderr="",
        )
        with (
            mock.patch.object(ADAPTER.subprocess, "run", return_value=response),
            mock.patch.object(
                ADAPTER, "secure_plugin_dir", side_effect=lambda path: path
            ),
            mock.patch.object(
                ADAPTER, "plugin_tree_digest", side_effect=["same", "same"]
            ),
        ):
            ADAPTER.installed_plugin(Path("/synthetic/codex"), version)

    def test_plugin_tree_digest_covers_contents_and_executable_modes(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-plugin-tree-") as raw:
            root = private(Path(raw))
            first = private(root / "first")
            second = private(root / "second")
            (first / "runtime.py").write_text("same\n", encoding="utf-8")
            (second / "runtime.py").write_text("same\n", encoding="utf-8")
            os.chmod(first / "runtime.py", 0o600)
            os.chmod(second / "runtime.py", 0o600)
            self.assertEqual(
                ADAPTER.plugin_tree_digest(first),
                ADAPTER.plugin_tree_digest(second),
            )
            os.chmod(second / "runtime.py", 0o700)
            self.assertNotEqual(
                ADAPTER.plugin_tree_digest(first),
                ADAPTER.plugin_tree_digest(second),
            )

    def test_stop_disarms_and_targets_only_recorded_isolated_processes(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-stop-") as raw:
            root = private(Path(raw))
            fake = write_executable(root / "fake-codex", "#!/bin/sh\nexit 0\n")
            token = "stop-token"
            session = self.full_session(
                instance=root,
                fake_codex=fake,
                token=token,
                now=ADAPTER.utc_now(),
            )
            session.update(
                {
                    "desktop_pid": 4101,
                    "proxy_pid": 4102,
                    "app_server_pid": 4103,
                }
            )
            ADAPTER.atomic_private_json(root / "session.json", session)
            commands = {
                4101: f"{fake} {session['desktop_isolation_argument']}",
                4102: f"{ADAPTER_PATH} app-server",
                4103: f"{fake} app-server",
            }
            observations: dict[int, int] = {}

            def fake_process_command(pid):
                observations[pid] = observations.get(pid, 0) + 1
                return commands.get(pid) if observations[pid] == 1 else None

            with (
                mock.patch.object(
                    ADAPTER, "process_command", side_effect=fake_process_command
                ),
                mock.patch.object(ADAPTER.os, "kill") as kill,
            ):
                result = ADAPTER.stop(root, timeout=0)
            self.assertTrue(result["ok"])
            self.assertEqual(
                [
                    mock.call(4101, ADAPTER.signal.SIGTERM),
                    mock.call(4102, ADAPTER.signal.SIGTERM),
                    mock.call(4103, ADAPTER.signal.SIGTERM),
                ],
                kill.call_args_list,
            )
            self.assertFalse(
                ADAPTER.read_private_json(root / "session.json")["armed"]
            )

    def test_stop_never_signals_desktop_with_prefix_collision_isolation(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-host-stop-collision-") as raw:
            root = private(Path(raw))
            fake = write_executable(root / "fake-codex", "#!/bin/sh\nexit 0\n")
            session = self.full_session(
                instance=root,
                fake_codex=fake,
                token="stop-collision-token",
                now=ADAPTER.utc_now(),
            )
            session["desktop_pid"] = 4301
            ADAPTER.atomic_private_json(root / "session.json", session)
            collision = f"{fake} {session['desktop_isolation_argument']}-other"
            with (
                mock.patch.object(ADAPTER, "process_command", return_value=collision),
                mock.patch.object(ADAPTER.os, "kill") as kill,
            ):
                result = ADAPTER.stop(root, timeout=0)
            self.assertTrue(result["ok"])
            self.assertEqual([], result["result"]["signaled_pids"])
            kill.assert_not_called()
            self.assertFalse(
                ADAPTER.read_private_json(root / "session.json")["armed"]
            )


if __name__ == "__main__":
    unittest.main()
