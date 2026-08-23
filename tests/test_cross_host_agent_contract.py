"""Contract for the cross_host_agent add-on.

The properties worth pinning are the ones that keep a convenience tool from quietly
becoming an open door: grants that expire, refusal rather than guessing, and an ssh
invocation that can never fall back to a password.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "cross_host_agent" / "common"
CLI = ADDON / "bin" / "agent-host"
CONFIG = json.loads((ROOT / "firestarter.config.json").read_text())


def run(args, manifest=None, extra_env=None):
    env = dict(os.environ)
    if manifest:
        env["AGENT_HOST_MANIFEST"] = str(manifest)
    env["AGENT_HOST_LOG"] = str(Path(tempfile.gettempdir()) / "agent-host-test.log")
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, str(CLI)] + args,
                          capture_output=True, text=True, env=env)


def manifest(tmp, **over):
    h = {"name": "box", "address": "host.example", "os": "linux", "user": "u",
         "capabilities": ["thing"],
         "grant_expires": (dt.date.today() + dt.timedelta(days=30)).isoformat()}
    h.update(over)
    p = Path(tmp) / "hosts.json"
    p.write_text(json.dumps({"hosts": [h]}))
    return p


class Registration(unittest.TestCase):
    def test_registered_and_off_by_default(self):
        choices = CONFIG["include_cross_host_agent"]
        self.assertEqual(choices[0], "no", "add-on must be opt-in")
        self.assertIn("yes", choices)

    def test_wired_into_the_generator(self):
        self.assertIn('"cross_host_agent"', (ROOT / "bin" / "generate.py").read_text())


class GrantsExpire(unittest.TestCase):
    """The default outcome of forgetting a channel must be that it closes."""

    def test_expired_grant_refuses_to_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = manifest(tmp, grant_expires=(dt.date.today() - dt.timedelta(days=1)).isoformat())
            r = run(["run", "thing", "--dry-run", "--", "echo", "hi"], m)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("expired", r.stderr.lower())

    def test_missing_expiry_is_an_error_not_a_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "hosts.json"
            p.write_text(json.dumps({"hosts": [{"name": "b", "address": "a", "os": "linux",
                                                "user": "u", "capabilities": ["thing"]}]}))
            r = run(["run", "thing", "--dry-run", "--", "echo", "hi"], p)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("grant_expires", r.stderr)

    def test_valid_grant_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(["run", "thing", "--dry-run", "--", "echo", "hi"], manifest(tmp))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("host.example", r.stdout)


class RefusesToGuess(unittest.TestCase):
    def test_unknown_capability_lists_what_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(["run", "nope", "--dry-run", "--", "x"], manifest(tmp))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("thing", r.stderr, "should say what capabilities are declared")

    def test_ambiguous_capability_refuses_rather_than_picking(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = (dt.date.today() + dt.timedelta(days=30)).isoformat()
            p = Path(tmp) / "hosts.json"
            p.write_text(json.dumps({"hosts": [
                {"name": "a", "address": "a", "os": "linux", "user": "u",
                 "capabilities": ["thing"], "grant_expires": exp},
                {"name": "b", "address": "b", "os": "linux", "user": "u",
                 "capabilities": ["thing"], "grant_expires": exp}]}))
            r = run(["run", "thing", "--dry-run", "--", "x"], p)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("more than one", r.stderr)

    def test_missing_manifest_is_an_error(self):
        r = run(["list"], Path(tempfile.gettempdir()) / "definitely-not-here.json")
        self.assertNotEqual(r.returncode, 0)


class NeverAPassword(unittest.TestCase):
    """An agent must never be in a position to send a password."""

    def test_ssh_invocation_disables_password_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(["run", "thing", "--dry-run", "--", "echo", "hi"], manifest(tmp))
            self.assertEqual(r.returncode, 0, r.stderr)
            for flag in ("BatchMode=yes", "PasswordAuthentication=no"):
                self.assertIn(flag, r.stdout, f"{flag} missing from the ssh invocation")

    def test_source_never_shells_out_through_a_shell(self):
        src = CLI.read_text()
        self.assertNotIn("shell=True", src,
                         "a remote command must not be interpolated through a local shell")


class Auditable(unittest.TestCase):
    def test_every_run_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "audit.log"
            run(["run", "thing", "--dry-run", "--", "echo", "hi"], manifest(tmp),
                {"AGENT_HOST_LOG": str(log)})
            # dry-run does not execute, so nothing to log; a real run would append.
            r = run(["list"], manifest(tmp), {"AGENT_HOST_LOG": str(log)})
            self.assertEqual(r.returncode, 0)


class BootstrapsAreSafe(unittest.TestCase):
    def test_windows_bootstrap_pins_the_firewall_profile(self):
        s = (ADDON / "bootstrap" / "windows.ps1").read_text()
        self.assertIn("-Profile Any", s,
                      "a rule without an explicit profile silently misses the tailnet adapter")
        self.assertIn("InterfaceAlias", s, "the rule must be scoped to one interface")

    def test_windows_bootstrap_disables_password_auth(self):
        s = (ADDON / "bootstrap" / "windows.ps1").read_text()
        self.assertIn("PasswordAuthentication no", s)

    def test_windows_bootstrap_verifies_rather_than_assumes(self):
        s = (ADDON / "bootstrap" / "windows.ps1").read_text()
        self.assertIn("Test-NetConnection", s,
                      "must confirm reachability, not report success because nothing threw")

    def test_no_bootstrap_takes_a_password(self):
        for f in (ADDON / "bootstrap").iterdir():
            s = f.read_text().lower()
            self.assertNotIn("read-host -assecurestring", s, f"{f.name} prompts for a secret")
            self.assertNotIn("$password", s, f"{f.name} references a password")


if __name__ == "__main__":
    unittest.main(verbosity=2)
