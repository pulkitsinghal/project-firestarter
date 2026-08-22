"""Offline generator and adversarial contract for trusted_workstation phase 1."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional
import unittest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "bin" / "generate.py"
ADDON = ROOT / "addons" / "trusted_workstation" / "common"
FIXTURES = ROOT / "tests" / "fixtures" / "trusted_workstation_ledgers"
FIXTURE_REPOSITORY = "Example-Org/sample-repo"
EXPECTED = (
    "trusted-workstation/policy.json",
    "trusted-workstation/enrollment-ledger.schema.json",
    "trusted-workstation/repository.txt",
    "scripts/trusted-workstation-doctor.sh",
    "scripts/trusted-workstation-status.sh",
    "scripts/trusted-workstation-doctor.ps1",
    "scripts/trusted-workstation-status.ps1",
    "scripts/trusted-workstation-ledger-validator.js",
    "docs/TRUSTED_WORKSTATION.md",
)


def stamp(output: Path, *sets: str) -> None:
    args = [sys.executable, str(GENERATOR), "--defaults", "--output", str(output)]
    for value in sets:
        args += ["--set", value]
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    subprocess.run(
        args, cwd=ROOT, check=True, capture_output=True, encoding="utf-8",
        errors="strict", env=env,
    )


def usable_bash() -> Optional[str]:
    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        probe = subprocess.run(
            [bash, "--version"], capture_output=True, encoding="utf-8",
            errors="strict", timeout=10,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    return bash if probe.returncode == 0 and "bash" in probe.stdout.lower() else None


class TrustedWorkstationContractTests(unittest.TestCase):
    def test_custom_auto_merge_requires_exact_macos_behavior_check(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "auto-merge.yml").read_text()
        match = re.search(r"const alwaysRequired = \[(.*?)\];", workflow, re.DOTALL)
        self.assertIsNotNone(match, "custom auto-merge required-check list is missing")
        required = re.findall(r"'([^']+)'", match.group(1))
        self.assertIn("Trusted Workstation macOS Behavior", required)
        self.assertEqual(required.count("Trusted Workstation macOS Behavior"), 1)
        self.assertIn(
            "name: Trusted Workstation macOS Behavior",
            (ROOT / ".github" / "workflows" / "ci.yml").read_text(),
        )

    def test_default_off_and_registered(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text())
        self.assertEqual(config["include_trusted_workstation"], ["no", "yes"])
        self.assertEqual(
            config["trusted_workstation_repo"], "{{ github_owner }}/{{ github_repo }}"
        )
        self.assertIn('"trusted_workstation"', GENERATOR.read_text())
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "off"
            stamp(output)
            self.assertFalse((output / "trusted-workstation").exists())
            self.assertFalse((output / "scripts/trusted-workstation-doctor.sh").exists())

    def test_every_stack_stamps_valid_contract_without_token_leaks(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            for stack in config["stack"]:
                with self.subTest(stack=stack):
                    output = Path(temp) / stack
                    stamp(
                        output,
                        f"stack={stack}",
                        "include_trusted_workstation=yes",
                        "github_owner=Auggie-Health-Inc",
                        "github_repo=Auggie-Home",
                    )
                    for rel in EXPECTED:
                        path = output / rel
                        self.assertTrue(path.is_file(), f"missing {stack}:{rel}")
                        self.assertNotIn("{{", path.read_text(), f"token leak {stack}:{rel}")
                    policy = json.loads((output / EXPECTED[0]).read_text())
                    schema = json.loads((output / EXPECTED[1]).read_text())
                    self.assertEqual(policy["repositorySource"], "repository.txt")
                    self.assertEqual(
                        schema["properties"]["repository"]["const"],
                        "Auggie-Health-Inc/Auggie-Home",
                    )
                    self.assertEqual(
                        (output / "trusted-workstation" / "repository.txt").read_text(encoding="ascii"),
                        "Auggie-Health-Inc/Auggie-Home\n",
                    )

    def test_security_sensitive_repository_syntax_is_strict(self) -> None:
        invalid = (
            "owner",
            "/repo",
            "owner/",
            "owner/.",
            "-owner/repo",
            "owner-/repo",
            "owner/..",
            "owner/repo;touch-pwned",
            "owner/repo'quoted",
            'owner/repo"quoted',
            "owner/$()",
            "owner/`id`",
            "owner/repo\rnext",
            "owner/repo\nnext",
            "owner/répo",
            "owner/repo\x1b",
        )
        with tempfile.TemporaryDirectory() as temp:
            for index, repository in enumerate(invalid):
                with self.subTest(repository=repr(repository)):
                    with self.assertRaises(subprocess.CalledProcessError):
                        stamp(
                            Path(temp) / str(index),
                            "include_trusted_workstation=yes",
                            f"trusted_workstation_repo={repository}",
                        )

    def test_adversarial_project_names_never_enter_executable_addon_source(self) -> None:
        names = (
            "quote\"name",
            "apostrophe'name",
            "dollar$(touch pwned)",
            "backtick`id`",
            "semi;colon",
            "line\rbreak",
            "line\nbreak",
            "snowman-☃",
            "escape-\x1b",
            r"replacement\1",
        )
        executable_names = (
            "trusted-workstation-doctor.sh",
            "trusted-workstation-status.sh",
            "trusted-workstation-doctor.ps1",
            "trusted-workstation-status.ps1",
            "trusted-workstation-ledger-validator.js",
        )
        with tempfile.TemporaryDirectory() as temp:
            for index, name in enumerate(names):
                with self.subTest(name=repr(name)):
                    output = Path(temp) / str(index)
                    stamp(
                        output,
                        "include_trusted_workstation=yes",
                        f"project_name={name}",
                        f"project_tagline={name}",
                        "github_owner=Example-Org",
                        "github_repo=sample-repo",
                    )
                    for script_name in executable_names:
                        text = (output / "scripts" / script_name).read_text(encoding="utf-8")
                        self.assertNotIn(name, text)
                        self.assertNotIn("{{", text)

    def test_shared_fixture_corpus_matches_draft_2020_12_schema(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError as error:
            self.fail(f"jsonschema is required for the contract gate: {error}")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "stamped"
            stamp(
                output,
                "include_trusted_workstation=yes",
                f"trusted_workstation_repo={FIXTURE_REPOSITORY}",
            )
            schema = json.loads(
                (output / "trusted-workstation" / "enrollment-ledger.schema.json").read_text()
            )
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)

            def strict_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate key")
                    result[key] = value
                return result

            for path in sorted((FIXTURES / "accepted").glob("*.json")):
                with self.subTest(fixture=path.name):
                    instance = json.loads(path.read_text(), object_pairs_hook=strict_object)
                    self.assertEqual(list(validator.iter_errors(instance)), [])
            for path in sorted((FIXTURES / "rejected").glob("*.json")):
                with self.subTest(fixture=path.name):
                    try:
                        instance = json.loads(path.read_text(), object_pairs_hook=strict_object)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    self.assertTrue(list(validator.iter_errors(instance)), path.name)

    def test_platform_validator_matches_shared_fixture_corpus(self) -> None:
        if os.name == "nt":
            runtime = shutil.which("cscript")
            command = lambda validator, ledger: [runtime, "//nologo", str(validator), str(ledger), FIXTURE_REPOSITORY]
        elif sys.platform == "darwin":
            runtime = "/usr/bin/osascript"
            command = lambda validator, ledger: [runtime, "-l", "JavaScript", str(validator), str(ledger), FIXTURE_REPOSITORY]
        else:
            self.skipTest("platform validator is available on Windows and macOS")
        self.assertTrue(runtime and Path(runtime).exists(), "platform JavaScript runtime is unavailable")
        validator = ADDON / "scripts" / "trusted-workstation-ledger-validator.js"
        for accept, directory in ((True, "accepted"), (False, "rejected")):
            for ledger in sorted((FIXTURES / directory).glob("*.json")):
                with self.subTest(fixture=ledger.name):
                    before = ledger.read_bytes()
                    result = subprocess.run(command(validator, ledger), capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode == 0, accept, result.stdout + result.stderr)
                    self.assertEqual(ledger.read_bytes(), before)

    def test_phase_one_authority_is_read_only(self) -> None:
        policy = json.loads((ADDON / "trusted-workstation" / "policy.json").read_text())
        authority = policy["authority"]
        self.assertTrue(authority["mayInspectClone"])
        self.assertTrue(authority["mayReadLedger"])
        for capability, allowed in authority.items():
            if capability not in {"mayInspectClone", "mayReadLedger"}:
                self.assertFalse(allowed, capability)
        exclusions = policy["futureEnrollment"]["mutagenMandatoryExclusions"]
        for required in (".git", ".git/**", ".git-crypt/**", "*.key", "*.git-crypt.key"):
            self.assertIn(required, exclusions)

    def test_scripts_contain_no_forbidden_mutations_or_secret_reads(self) -> None:
        scripts = "\n".join(
            path.read_text()
            for path in (ADDON / "scripts").iterdir()
            if path.is_file()
        ).lower()
        forbidden = (
            "op read",
            "op item get",
            "tailscale up",
            "tailscale set",
            "tailscale ssh",
            "tailscale serve",
            "tailscale funnel",
            "mutagen sync create",
            "git config core.hookspath",
            "new-netfirewallrule",
            "set-netfirewallprofile",
            "systemctl enable",
            "launchctl load",
        )
        for phrase in forbidden:
            self.assertNotIn(phrase, scripts, phrase)

    def test_shell_syntax(self) -> None:
        bash = usable_bash()
        if not bash:
            self.skipTest("bash unavailable")
        for path in (ADDON / "scripts").glob("*.sh"):
            subprocess.run([bash, "-n", str(path)], check=True)

    def test_doctor_accepts_clone_and_rejects_linked_worktree(self) -> None:
        bash = usable_bash()
        if not bash:
            self.skipTest("bash unavailable")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            stamped = base / "stamped"
            stamp(
                stamped,
                "include_trusted_workstation=yes",
                "github_owner=Auggie-Health-Inc",
                "github_repo=Auggie-Home",
            )
            repo = base / "clone"
            (repo / ".git").mkdir(parents=True)
            fake_bin = base / "bin"
            fake_bin.mkdir()
            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/bin/sh\n"
                "case \"$*\" in\n"
                "  'rev-parse --show-toplevel') printf '%s\\n' \"$FAKE_ROOT\" ;;\n"
                "  'rev-parse --absolute-git-dir')\n"
                "    if [ \"${FAKE_LINKED:-0}\" = 1 ]; then printf '%s\\n' \"$FAKE_ROOT/../external.git\"; else printf '%s\\n' \"$FAKE_ROOT/.git\"; fi ;;\n"
                "  'rev-parse --git-common-dir') if [ \"${FAKE_LINKED:-0}\" = 1 ]; then printf '%s\\n' \"$FAKE_ROOT/../external.git\"; else printf '%s\\n' '.git'; fi ;;\n"
                "  'remote get-url origin') printf '%s\\n' 'https://github.com/Auggie-Health-Inc/Auggie-Home.git' ;;\n"
                "  'config --local --get core.hooksPath') printf '%s\\n' '.githooks' ;;\n"
                "  *) exit 98 ;;\n"
                "esac\n"
            )
            fake_git.chmod(0o755)
            for name in ("git-crypt", "op", "tailscale"):
                tool = fake_bin / name
                tool.write_text("#!/bin/sh\nexit 99\n")
                tool.chmod(0o755)
            env = {
                **dict(__import__("os").environ),
                "PATH": f"{fake_bin}:{__import__('os').environ.get('PATH', '')}",
                "FAKE_ROOT": str(repo),
            }
            doctor = stamped / "scripts" / "trusted-workstation-doctor.sh"
            accepted = subprocess.run([bash, str(doctor)], cwd=repo, env=env, capture_output=True, text=True)
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            rejected = subprocess.run(
                [bash, str(doctor)], cwd=repo, env={**env, "FAKE_LINKED": "1"}, capture_output=True, text=True
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("linked, external, or shared", rejected.stdout)
            repository_file = stamped / "trusted-workstation" / "repository.txt"
            repository_file.write_text("Example-Org/.\n", encoding="ascii")
            invalid_repository = subprocess.run(
                [bash, str(doctor)], cwd=repo, env=env, capture_output=True, text=True
            )
            self.assertEqual(invalid_repository.returncode, 2)
            self.assertIn("repository configuration is invalid", invalid_repository.stderr)

    def test_powershell_scripts_parse(self) -> None:
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            self.skipTest("PowerShell unavailable")
        for path in (ADDON / "scripts").glob("*.ps1"):
            command = (
                "$e=$null;$t=$null;[System.Management.Automation.Language.Parser]::"
                f"ParseFile('{path}',[ref]$t,[ref]$e)|Out-Null;if($e.Count){{exit 1}}"
            )
            subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)

    def test_windows_native_behavior_harness(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-only behavior harness")
        powershell = shutil.which("powershell")
        if not powershell:
            self.fail("Windows PowerShell is unavailable")
        subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tests" / "trusted_workstation_windows.ps1")],
            cwd=ROOT,
            check=True,
            timeout=60,
        )

    def test_macos_native_behavior_harness(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("macOS-only behavior harness")
        subprocess.run(
            ["/bin/bash", str(ROOT / "tests" / "trusted_workstation_macos.sh")],
            cwd=ROOT,
            check=True,
            timeout=60,
        )


if __name__ == "__main__":
    unittest.main()
