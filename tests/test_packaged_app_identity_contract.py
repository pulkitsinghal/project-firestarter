"""Generator + behaviour contract for the packaged_app_identity add-on.

Proves the add-on is off by default, stamps cleanly for every declared stack
with no token leaks, that the verifier is stdlib-only and OBSERVE/PLAN ONLY (it
holds no process-execution primitive, so the exact-pid stop plan can never
become a process-name kill), and that each verdict behaves correctly against
synthetic property lists without leaking a plist body or a full filesystem path.

The one host-only step — `acceptance.sh`, which uses `codesign` against a signed
bundle — is exercised hermetically on any platform with fake `uname` / `codesign`
executables on PATH, and its off-macOS skip path is checked directly.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "packaged_app_identity" / "common"
TOOL = ADDON / "tools" / "packaged_app_identity"
GENERATOR = ROOT / "bin" / "generate.py"
CONFIG = json.loads((ROOT / "firestarter.config.json").read_text())

# The only legitimate "{{" in generated output is a GitHub expression or JSX;
# neither appears in this add-on's files, so any "{{" here is a real leak.
LEAK = re.compile(r"\{\{")

PLIST_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    '<plist version="1.0">\n<dict>\n'
)
PLIST_TAIL = "</dict>\n</plist>\n"

ENT_KEY = "com.apple.security.automation.apple-events"
USAGE_KEY = "NSAppleEventsUsageDescription"

# A planted marker inside each synthetic plist body. Content suppression means it
# must never reach stdout/stderr — the verifier reports key names only.
SECRET = "DO-NOT-LEAK-THIS-MARKER"


def _entitlements(*, present: bool, enabled: bool = True) -> str:
    body = f"  <key>com.example.private</key>\n  <string>{SECRET}</string>\n"
    if present:
        body += f"  <key>{ENT_KEY}</key>\n  {'<true/>' if enabled else '<false/>'}\n"
    return PLIST_HEAD + body + PLIST_TAIL


def _info_plist(usage: str | None) -> str:
    body = f"  <key>NSHumanReadableCopyright</key>\n  <string>{SECRET}</string>\n"
    body += "  <key>CFBundleIdentifier</key>\n  <string>com.example.app</string>\n"
    if usage is not None:
        body += f"  <key>{USAGE_KEY}</key>\n  <string>{usage}</string>\n"
    return PLIST_HEAD + body + PLIST_TAIL


def _stamp(output: Path, stack: str, *, enable: bool) -> None:
    args = [
        sys.executable, str(GENERATOR), "--defaults",
        "--set", f"stack={stack}",
        "--output", str(output),
    ]
    if enable:
        args += ["--set", "include_packaged_app_identity=yes"]
    subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)


class PackagedAppIdentityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name) / "app"
        _stamp(out, "fastapi-next", enable=True)
        cls.verify = out / "tools" / "packaged_app_identity" / "verify.py"
        cls.acceptance = out / "tools" / "packaged_app_identity" / "acceptance.sh"
        assert cls.verify.is_file(), cls.verify
        assert cls.acceptance.is_file(), cls.acceptance

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # -- helpers ---------------------------------------------------------------

    def _verify(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(self.verify), *argv],
            check=False, capture_output=True, text=True, timeout=60,
        )

    def _plist_file(self, text: str) -> str:
        path = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        target = path / "plist"
        target.write_text(text)
        return str(target)

    def _run_acceptance(self, *, app, darwin, codesign_xml=None,
                        codesign_fail=False, args=None) -> subprocess.CompletedProcess:
        shim = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, shim, ignore_errors=True)

        def write_shim(name: str, body: str) -> None:
            path = shim / name
            path.write_text(body)
            path.chmod(0o755)

        write_shim("python3", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        if darwin:
            write_shim("uname", "#!/bin/sh\necho Darwin\n")
            if codesign_fail:
                write_shim("codesign", "#!/bin/sh\nexit 1\n")
            elif codesign_xml is not None:
                xml = shim / "ent.xml"
                xml.write_text(codesign_xml)
                write_shim("codesign", f'#!/bin/sh\ncat "{xml}"\n')

        env = {"PATH": f"{shim}:/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}
        argv = args if args is not None else ["--app", str(app)]
        return subprocess.run(
            ["bash", str(self.acceptance), *argv],
            check=False, capture_output=True, text=True, timeout=60, env=env,
        )

    def _make_app(self, usage: str | None) -> Path:
        app = Path(tempfile.mkdtemp()) / "Example.app"
        self.addCleanup(shutil.rmtree, app.parent, ignore_errors=True)
        (app / "Contents").mkdir(parents=True)
        (app / "Contents" / "Info.plist").write_text(_info_plist(usage))
        return app

    # -- registration & stamping ----------------------------------------------

    def test_registered_as_closed_choice_and_off_by_default(self) -> None:
        self.assertEqual(CONFIG["include_packaged_app_identity"], ["no", "yes"])
        self.assertIn('"packaged_app_identity"', GENERATOR.read_text())

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "default"
            _stamp(output, "fastapi-next", enable=False)
            self.assertFalse((output / "tools" / "packaged_app_identity").exists())

    def test_every_stack_stamps_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for stack in CONFIG["stack"]:
                with self.subTest(stack=stack):
                    output = root / stack
                    _stamp(output, stack, enable=True)
                    tool = output / "tools" / "packaged_app_identity"
                    verify = tool / "verify.py"
                    acceptance = tool / "acceptance.sh"
                    doc = output / "docs" / "PACKAGED_APP_IDENTITY.md"
                    for path in (verify, acceptance, doc):
                        self.assertTrue(path.is_file(), path)
                    for path in tool.rglob("*"):
                        if path.is_file():
                            self.assertIsNone(
                                LEAK.search(path.read_text(encoding="utf-8", errors="ignore")),
                                f"token leak in {path}",
                            )
                    subprocess.run(
                        [sys.executable, "-m", "py_compile", str(verify)],
                        check=True, capture_output=True, text=True,
                    )
                    subprocess.run(
                        ["bash", "-n", str(acceptance)],
                        check=True, capture_output=True, text=True,
                    )

    # -- source posture --------------------------------------------------------

    def test_tool_is_stdlib_only(self) -> None:
        src = (TOOL / "verify.py").read_text()
        for banned in ("import requests", "import httpx", "import aiohttp",
                       "import yaml", "requests.", "httpx."):
            self.assertNotIn(banned, src)

    def test_verifier_holds_no_process_execution_primitive(self) -> None:
        # The stop plan can only ever name one pid because this module cannot
        # execute anything: no signal send, no shell-out, no process-name kill.
        src = (TOOL / "verify.py").read_text()
        for banned in ("os.kill", "os.system", "os.popen",
                       "import subprocess", "subprocess.", "import signal"):
            self.assertNotIn(banned, src)

    # -- entitlement -----------------------------------------------------------

    def test_entitlement_present_and_enabled_passes(self) -> None:
        result = self._verify("entitlement", "--entitlements",
                              self._plist_file(_entitlements(present=True)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_entitlement_absent_fails_without_leaking_body(self) -> None:
        result = self._verify("entitlement", "--entitlements",
                              self._plist_file(_entitlements(present=False)))
        self.assertEqual(result.returncode, 1)
        self.assertIn("absent", result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_entitlement_present_but_disabled_fails(self) -> None:
        result = self._verify("entitlement", "--entitlements",
                              self._plist_file(_entitlements(present=True, enabled=False)))
        self.assertEqual(result.returncode, 1)
        self.assertIn("not enabled", result.stderr)

    def test_entitlement_malformed_plist_is_usage_error(self) -> None:
        result = self._verify("entitlement", "--entitlements",
                              self._plist_file("this is not a property list"))
        self.assertEqual(result.returncode, 2)

    def test_malformed_xml_with_header_is_bounded_not_a_traceback(self) -> None:
        # A malformed plist that still carries an <?xml header routes through the
        # XML parser (expat), which raises a type that is NOT a ValueError; the
        # loader must still exit 2 with a bounded message -- never a traceback,
        # and never an echo of the (malformed) body. Both subcommands share the
        # loader, so both are checked. The secret is planted in the broken body.
        malformed = f'<?xml version="1.0"?>\n<plist version="1.0"><dict><key>{SECRET}</key><string>x\n'
        for sub, flag in (("entitlement", "--entitlements"),
                          ("usage-description", "--info-plist")):
            with self.subTest(subcommand=sub):
                result = self._verify(sub, flag, self._plist_file(malformed))
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn(SECRET, result.stdout + result.stderr)

    # -- usage description -----------------------------------------------------

    def test_usage_description_present_passes(self) -> None:
        result = self._verify("usage-description", "--info-plist",
                              self._plist_file(_info_plist("Automates another app for you.")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_usage_description_empty_fails(self) -> None:
        result = self._verify("usage-description", "--info-plist",
                              self._plist_file(_info_plist("")))
        self.assertEqual(result.returncode, 1)
        self.assertIn("empty", result.stderr)

    def test_usage_description_absent_fails(self) -> None:
        result = self._verify("usage-description", "--info-plist",
                              self._plist_file(_info_plist(None)))
        self.assertEqual(result.returncode, 1)
        self.assertIn("absent", result.stderr)

    # -- running-vs-installed identity -----------------------------------------

    def test_identity_inside_and_matching_passes(self) -> None:
        result = self._verify(
            "identity",
            "--running-exec", "/Applications/Example.app/Contents/MacOS/Example",
            "--bundle", "/Applications/Example.app",
            "--running-identity", "2.3.1+ab12cd", "--bundle-identity", "2.3.1+ab12cd",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_identity_stale_outside_bundle_fails_without_path_leak(self) -> None:
        private = "/Users/privateperson/Library/Caches/stale"
        result = self._verify(
            "identity",
            "--running-exec", f"{private}/Example.app/Contents/MacOS/Example",
            "--bundle", "/Applications/Example.app",
            "--running-identity", "2.3.1+ab12cd", "--bundle-identity", "2.3.1+ab12cd",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside the installed bundle", result.stderr)
        out = result.stdout + result.stderr
        self.assertNotIn("privateperson", out)
        self.assertNotIn(private, out)

    def test_identity_mismatched_build_fails(self) -> None:
        result = self._verify(
            "identity",
            "--running-exec", "/Applications/Example.app/Contents/MacOS/Example",
            "--bundle", "/Applications/Example.app",
            "--running-identity", "2.3.0+oldrev", "--bundle-identity", "2.3.1+ab12cd",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match", result.stderr)

    def test_identity_empty_identity_is_usage_error(self) -> None:
        result = self._verify(
            "identity",
            "--running-exec", "/Applications/Example.app/Contents/MacOS/Example",
            "--bundle", "/Applications/Example.app",
            "--running-identity", "", "--bundle-identity", "2.3.1+ab12cd",
        )
        self.assertEqual(result.returncode, 2)

    def test_identity_empty_paths_are_usage_error(self) -> None:
        # Empty --running-exec/--bundle must not make the containment check
        # vacuously true (normpath("") -> "."); guard them symmetrically.
        result = self._verify(
            "identity",
            "--running-exec", "", "--bundle", "",
            "--running-identity", "2.3.1+ab12cd", "--bundle-identity", "2.3.1+ab12cd",
        )
        self.assertEqual(result.returncode, 2)

    # -- single-instance lock --------------------------------------------------

    def test_lock_check_current_build_passes(self) -> None:
        result = self._verify("lock-check", "--owner-identity", "2.3.1+ab12cd",
                              "--expected-identity", "2.3.1+ab12cd")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_lock_check_stale_owner_fails_visibly(self) -> None:
        result = self._verify("lock-check", "--owner-identity", "2.3.0+oldrev",
                              "--expected-identity", "2.3.1+ab12cd", "--owner-pid", "5150")
        self.assertEqual(result.returncode, 1)
        self.assertIn("stale process owns the single-instance lock", result.stderr)
        self.assertIn("5150", result.stderr)

    # -- exact-pid stop plan ---------------------------------------------------

    def test_stop_plan_targets_exact_pid_only(self) -> None:
        result = self._verify("stop-plan", "--pid", "4321")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["target_pid"], 4321)
        self.assertTrue(plan["non_executing"])
        for step in plan["steps"]:
            if "pid" in step:
                self.assertEqual(step["pid"], 4321)
        self.assertIn("exact pid only", plan["forbidden"])

    def test_stop_plan_rejects_nonpositive_pid(self) -> None:
        self.assertEqual(self._verify("stop-plan", "--pid", "0").returncode, 2)
        self.assertEqual(self._verify("stop-plan", "--pid", "-7").returncode, 2)

    # -- host-only acceptance (hermetic) ---------------------------------------

    def test_acceptance_skips_cleanly_off_macos(self) -> None:
        result = self._run_acceptance(app=self._make_app("ok"), darwin=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SKIP", result.stdout)

    def test_acceptance_passes_for_a_well_formed_signed_bundle(self) -> None:
        result = self._run_acceptance(
            app=self._make_app("Automates another app for you."),
            darwin=True, codesign_xml=_entitlements(present=True),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS packaged-app acceptance", result.stdout)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_acceptance_fails_when_entitlement_missing(self) -> None:
        result = self._run_acceptance(
            app=self._make_app("Automates another app for you."),
            darwin=True, codesign_xml=_entitlements(present=False),
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_acceptance_fails_when_usage_description_empty(self) -> None:
        result = self._run_acceptance(
            app=self._make_app(""), darwin=True,
            codesign_xml=_entitlements(present=True),
        )
        self.assertEqual(result.returncode, 1)

    def test_acceptance_fails_closed_on_unsigned_bundle(self) -> None:
        result = self._run_acceptance(
            app=self._make_app("ok"), darwin=True, codesign_fail=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("entitlements", result.stderr)

    def test_acceptance_requires_app_argument(self) -> None:
        result = self._run_acceptance(app=None, darwin=False, args=[])
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
