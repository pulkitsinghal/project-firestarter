"""Adversarial contract for deterministic source/release and vendored-byte parity."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "verify-release-parity.sh"
BASH = os.environ.get("RELEASE_PARITY_BASH", "bash")


class ReleaseParityBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name) / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        self.script = self.repo / "scripts" / "verify-release-parity.sh"
        shutil.copy2(SCRIPT, self.script)
        self.script.chmod(0o755)

    def write_bytes(self, relative: str, body: bytes) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def write_text(self, relative: str, body: str) -> Path:
        return self.write_bytes(relative, body.encode("utf-8"))

    def run_guard(
        self,
        *args: str,
        script: Path | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "LC_ALL": "C", **(env_extra or {})}
        return subprocess.run(
            [BASH, str(script or self.script), *args],
            cwd=self.repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

    @staticmethod
    def combined(result: subprocess.CompletedProcess[str]) -> str:
        return result.stdout + result.stderr

    def seed_pair(self, source_body: bytes, release_body: bytes) -> list[str]:
        self.write_bytes("assets/source.bin", source_body)
        self.write_bytes("dist/release.bin", release_body)
        self.write_text(
            "config/release-pairs.tsv",
            "# deterministic release assets\n"
            "assets/source.bin\tdist/release.bin\n",
        )
        return ["--pairs", "config/release-pairs.tsv"]

    def seed_vendor(self, body: bytes = b"synthetic vendor bytes\x00\n") -> list[str]:
        self.write_bytes("vendor/source/nested/library.bin", body)
        self.write_bytes("dist/vendor/nested/library.bin", body)
        digest = hashlib.sha256(body).hexdigest()
        self.write_text(
            "config/vendor.sha256.tsv",
            f"{digest}\tnested/library.bin\n",
        )
        return [
            "--vendor-manifest",
            "config/vendor.sha256.tsv",
            "--vendor-source",
            "vendor/source",
            "--vendor-release",
            "dist/vendor",
        ]

    def test_text_and_binary_pairs_require_exact_bytes(self) -> None:
        args = self.seed_pair(b"same\r\nbytes\x00", b"same\r\nbytes\x00")
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertIn("PASS pairs=1 vendor=0", result.stdout)

        self.write_bytes("dist/release.bin", b"same\nbytes\x00")
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr, r"^release-parity: FAIL violations=\d+\n$")

        self.write_bytes("dist/release.bin", b"same\r\nbytes\x00")
        self.write_bytes(
            "config/release-pairs.tsv",
            b"assets/source.bin\tdist/release.bin\r\n",
        )
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 0, self.combined(result))

    def test_pair_manifest_rejects_malformed_duplicate_unsafe_and_symlinked_rows(self) -> None:
        private_name = "PRIVATE_CUSTOMER_EXPORT_DO_NOT_LOG.bin"
        self.write_bytes(f"assets/{private_name}", b"private-shaped synthetic bytes")
        self.write_bytes("dist/release.bin", b"private-shaped synthetic bytes")
        self.write_text(
            "config/release-pairs.tsv",
            "malformed-row\n"
            f"assets/{private_name}\tdist/release.bin\n"
            f"ASSETS/{private_name}\tDIST/RELEASE.BIN\n"
            "../outside\tdist/release.bin\n"
            "/absolute\tdist/release.bin\n"
            "-option-like\tdist/release.bin\n"
            "assets/source.bin\tdist/release.bin\textra\n",
        )
        result = self.run_guard("--pairs", "config/release-pairs.tsv")
        self.assertEqual(result.returncode, 1)
        combined = self.combined(result)
        self.assertRegex(combined, r"^release-parity: FAIL violations=\d+\n$")
        self.assertNotIn(private_name, combined)
        self.assertNotIn("outside", combined)
        self.assertNotIn("absolute", combined)

        if hasattr(os, "symlink"):
            self.write_bytes("assets/target.bin", b"same")
            self.write_bytes("dist/target.bin", b"same")
            try:
                os.symlink("target.bin", self.repo / "assets" / "link.bin")
            except OSError:
                self.skipTest("symlink creation unavailable")
            self.write_text(
                "config/release-pairs.tsv",
                "assets/link.bin\tdist/target.bin\n",
            )
            result = self.run_guard("--pairs", "config/release-pairs.tsv")
            self.assertEqual(result.returncode, 1)

    def test_case_folded_duplicate_pairs_fail_even_when_both_rows_exist(self) -> None:
        self.write_bytes("assets/source.bin", b"same")
        self.write_bytes("dist/release.bin", b"same")
        self.write_bytes("ASSETS/SOURCE.BIN", b"same")
        self.write_bytes("DIST/RELEASE.BIN", b"same")
        self.write_text(
            "config/release-pairs.tsv",
            "assets/source.bin\tdist/release.bin\n"
            "ASSETS/SOURCE.BIN\tDIST/RELEASE.BIN\n",
        )
        result = self.run_guard("--pairs", "config/release-pairs.tsv")
        self.assertEqual(result.returncode, 1)

    def test_tab_bearing_hash_line_is_a_rejected_row_not_a_comment(self) -> None:
        self.write_bytes("assets/source.bin", b"same")
        self.write_bytes("dist/release.bin", b"same")
        self.write_bytes("#hidden-source.bin", b"source")
        self.write_bytes("dist/hidden-release.bin", b"release")
        self.write_text(
            "config/release-pairs.tsv",
            "# ordinary tab-free comment\n"
            "assets/source.bin\tdist/release.bin\n"
            "#hidden-source.bin\tdist/hidden-release.bin\n",
        )
        result = self.run_guard("--pairs", "config/release-pairs.tsv")
        self.assertEqual(result.returncode, 1)

    def test_single_row_case_drift_fails_on_case_sensitive_or_insensitive_hosts(self) -> None:
        self.write_bytes("Assets/Source.bin", b"same")
        self.write_bytes("Dist/Release.bin", b"same")
        self.write_text(
            "config/release-pairs.tsv",
            "assets/source.bin\tdist/release.bin\n",
        )
        result = self.run_guard("--pairs", "config/release-pairs.tsv")
        self.assertEqual(result.returncode, 1)

    def test_source_and_release_must_be_distinct_files_and_roots(self) -> None:
        self.write_bytes("assets/source.bin", b"same")
        self.write_text(
            "config/release-pairs.tsv",
            "assets/source.bin\tassets/source.bin\n",
        )
        result = self.run_guard("--pairs", "config/release-pairs.tsv")
        self.assertEqual(result.returncode, 1)

        vendor_args = self.seed_vendor()
        same_root_args = [
            "--vendor-manifest",
            "config/vendor.sha256.tsv",
            "--vendor-source",
            "vendor/source",
            "--vendor-release",
            "vendor/source",
        ]
        result = self.run_guard(*same_root_args)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.run_guard(*vendor_args).returncode, 0)

    def test_hard_linked_source_and_release_fail_when_supported(self) -> None:
        self.write_bytes("assets/source.bin", b"same")
        self.write_bytes("dist/release.bin", b"placeholder")
        try:
            (self.repo / "dist" / "release.bin").unlink()
            os.link(
                self.repo / "assets" / "source.bin",
                self.repo / "dist" / "release.bin",
            )
        except OSError:
            self.skipTest("hard-link creation unavailable")
        self.write_text(
            "config/release-pairs.tsv",
            "assets/source.bin\tdist/release.bin\n",
        )
        result = self.run_guard("--pairs", "config/release-pairs.tsv")
        self.assertEqual(result.returncode, 1)

    def test_vendor_manifest_locks_hash_bytes_and_exact_inventories(self) -> None:
        args = self.seed_vendor()
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertIn("PASS pairs=0 vendor=1", result.stdout)

        self.write_bytes("dist/vendor/unlisted.bin", b"extra")
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 1)
        (self.repo / "dist" / "vendor" / "unlisted.bin").unlink()

        self.write_bytes("dist/vendor/nested/library.bin", b"one-byte drift!")
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 1)
        self.write_bytes(
            "dist/vendor/nested/library.bin", b"synthetic vendor bytes\x00\n"
        )

        self.write_text(
            "config/vendor.sha256.tsv",
            f"{'0' * 64}\tnested/library.bin\n",
        )
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 1)

    def test_vendor_manifest_rejects_malformed_duplicate_traversal_missing_and_symlink(self) -> None:
        private_name = "PROPRIETARY_BLOB_NAME_DO_NOT_LOG.bin"
        body = b"synthetic"
        digest = hashlib.sha256(body).hexdigest()
        self.write_bytes(f"vendor/source/{private_name}", body)
        self.write_bytes(f"dist/vendor/{private_name}", body)
        self.write_text(
            "config/vendor.sha256.tsv",
            "not-a-hash\tmalformed.bin\n"
            f"{digest}\t{private_name}\n"
            f"{digest}\t{private_name.lower()}\n"
            f"{digest}\t../escape.bin\n"
            f"{digest}\tmissing.bin\n",
        )
        args = [
            "--vendor-manifest",
            "config/vendor.sha256.tsv",
            "--vendor-source",
            "vendor/source",
            "--vendor-release",
            "dist/vendor",
        ]
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 1)
        combined = self.combined(result)
        self.assertRegex(combined, r"^release-parity: FAIL violations=\d+\n$")
        self.assertNotIn(private_name, combined)
        self.assertNotIn("escape", combined)

        self.write_text(
            "config/vendor.sha256.tsv",
            f"{digest}\t{private_name}\n",
        )
        try:
            os.symlink(
                private_name,
                self.repo / "vendor" / "source" / "linked.bin",
            )
        except OSError:
            self.skipTest("symlink creation unavailable")
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(private_name, self.combined(result))

    def test_incomplete_or_empty_configuration_fails_closed(self) -> None:
        result = self.run_guard()
        self.assertEqual(result.returncode, 2)
        result = self.run_guard("--vendor-source", "vendor/source")
        self.assertEqual(result.returncode, 2)
        self.write_text("config/empty.tsv", "# no declared assets\n")
        result = self.run_guard("--pairs", "config/empty.tsv")
        self.assertEqual(result.returncode, 1)
        private_multiline = "config/PRIVATE_MANIFEST\nPATH.tsv"
        result = self.run_guard("--pairs", private_multiline)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("PRIVATE_MANIFEST", self.combined(result))
        self.assertNotIn("PATH.tsv", self.combined(result))

    def test_privacy_safe_diagnostics_hide_paths_content_and_hashes(self) -> None:
        private_name = "SECRET_LAUNCH_ASSET_DO_NOT_LOG.bin"
        private_body = b"super-secret-shaped-synthetic-value"
        args = self.seed_pair(private_body, b"different")
        source = self.repo / "assets" / "source.bin"
        private_source = source.with_name(private_name)
        source.rename(private_source)
        self.write_text(
            "config/release-pairs.tsv",
            f"assets/{private_name}\tdist/release.bin\n",
        )
        result = self.run_guard(*args)
        self.assertEqual(result.returncode, 1)
        combined = self.combined(result)
        self.assertNotIn(private_name, combined)
        self.assertNotIn(private_body.decode(), combined)
        self.assertNotIn(hashlib.sha256(private_body).hexdigest(), combined)
        self.assertNotIn(str(self.repo), combined)

    def test_degraded_tools_fail_closed_and_never_echo_tool_output(self) -> None:
        args = self.seed_pair(b"same", b"same")
        hash_tool = "sha256sum" if shutil.which("sha256sum") else "shasum"
        tools = (
            "cmp",
            "sort",
            "grep",
            "tr",
            "find",
            "mkdir",
            "rm",
            "rmdir",
            hash_tool,
        )
        safely_noisy = {"cmp", "grep", "mkdir", "rm", "rmdir"}
        original_path = os.environ.get("PATH", "")
        for tool in tools:
            actual = shutil.which(tool)
            self.assertIsNotNone(actual, tool)
            for mode in ("noop", "fail", "noisy"):
                with self.subTest(tool=tool, mode=mode):
                    shim_dir = self.repo / "shims" / tool / mode
                    shim_dir.mkdir(parents=True)
                    shim = shim_dir / tool
                    secret = f"PRIVATE_TOOL_OUTPUT_{tool}_{mode}"
                    if mode == "noop":
                        body = "#!/bin/sh\nexit 0\n"
                    elif mode == "fail":
                        body = (
                            "#!/bin/sh\n"
                            f"printf '%s\\n' '{secret}'\n"
                            f"printf '%s\\n' '{secret}' >&2\n"
                            "exit 9\n"
                        )
                    else:
                        body = (
                            "#!/bin/sh\n"
                            f"printf '%s\\n' '{secret}'\n"
                            f"printf '%s\\n' '{secret}' >&2\n"
                            f"exec '{actual}' \"$@\"\n"
                        )
                    shim.write_text(body, encoding="utf-8")
                    shim.chmod(0o755)
                    temp_parent = self.repo / "tool-temp" / tool / mode
                    temp_parent.mkdir(parents=True)
                    result = self.run_guard(
                        *args,
                        env_extra={
                            "PATH": f"{shim_dir}{os.pathsep}{original_path}",
                            "TMPDIR": str(temp_parent),
                        },
                    )
                    if mode == "noisy" and tool in safely_noisy:
                        self.assertEqual(result.returncode, 0, self.combined(result))
                    else:
                        self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(secret, self.combined(result))
                    shutil.rmtree(temp_parent, ignore_errors=True)

    def test_create_then_fail_mkdir_removes_every_actual_candidate(self) -> None:
        args = self.seed_pair(b"same", b"same")
        temp_parent = self.repo / "mkdir-parent"
        temp_parent.mkdir()
        candidate_log = self.repo / "mkdir-candidates.txt"
        actual_mkdir = shutil.which("mkdir")
        self.assertIsNotNone(actual_mkdir)
        shim_dir = self.repo / "mkdir-create-then-fail-shim"
        shim_dir.mkdir()
        shim = shim_dir / "mkdir"
        shim.write_text(
            "#!/bin/sh\n"
            "last=\n"
            "for arg in \"$@\"; do last=$arg; done\n"
            f"printf '%s\\n' \"$last\" >> '{candidate_log}'\n"
            f"'{actual_mkdir}' \"$@\" || exit $?\n"
            "exit 9\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        result = self.run_guard(
            *args,
            env_extra={
                "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "TMPDIR": str(temp_parent),
            },
        )
        self.assertEqual(result.returncode, 2)
        candidates = [
            Path(value)
            for value in candidate_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(candidates), 32)
        expected_parent = Path("/tmp").resolve()
        process_ids: set[str] = set()
        attempts: list[int] = []
        for candidate in candidates:
            with self.subTest(candidate=candidate.name):
                prefix, process_id, attempt = candidate.name.split(".")
                self.assertEqual(prefix, "release-parity")
                self.assertTrue(process_id.isdigit())
                self.assertTrue(attempt.isdigit())
                self.assertEqual(candidate.parent.resolve(), expected_parent)
                self.assertFalse(candidate.exists() or candidate.is_symlink())
                process_ids.add(process_id)
                attempts.append(int(attempt))
        self.assertEqual(len(process_ids), 1)
        self.assertEqual(attempts, list(range(32)))
        self.assertFalse(any(temp_parent.glob("release-parity.*")))
        self.assertNotIn(str(temp_parent), self.combined(result))

    def run_with_manifest_removed_after_open(
        self, target: str, args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        actual_grep = shutil.which("grep")
        self.assertIsNotNone(actual_grep)
        shim_dir = self.repo / "manifest-removal-shim" / target.replace("/", "_")
        shim_dir.mkdir(parents=True)
        shim = shim_dir / "grep"
        target_path = self.repo / target
        seen_name = "vendor-seen" if "vendor" in target else "pair-seen"
        shim.write_text(
            "#!/bin/sh\n"
            f"case \"$*\" in *{seen_name}*) rm -f '{target_path}' ;; esac\n"
            f"exec '{actual_grep}' \"$@\"\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        return self.run_guard(
            *args,
            env_extra={
                "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            },
        )

    def test_manifests_are_opened_once_and_disappear_without_path_leaks(self) -> None:
        pair_args = self.seed_pair(b"same", b"same")
        self.write_bytes("assets/second.bin", b"second")
        self.write_bytes("dist/second.bin", b"second")
        self.write_text(
            "config/release-pairs.tsv",
            "assets/source.bin\tdist/release.bin\n"
            "assets/second.bin\tdist/second.bin\n",
        )
        result = self.run_with_manifest_removed_after_open(
            "config/release-pairs.tsv", pair_args
        )
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertIn("PASS pairs=2", result.stdout)
        self.assertFalse((self.repo / "config" / "release-pairs.tsv").exists())
        self.assertNotIn("release-pairs.tsv", self.combined(result))

        shutil.rmtree(self.repo / "assets")
        shutil.rmtree(self.repo / "dist")
        vendor_args = self.seed_vendor()
        second = b"second vendor"
        first_digest = hashlib.sha256(b"synthetic vendor bytes\x00\n").hexdigest()
        self.write_bytes("vendor/source/second.bin", second)
        self.write_bytes("dist/vendor/second.bin", second)
        self.write_text(
            "config/vendor.sha256.tsv",
            f"{first_digest}\tnested/library.bin\n"
            f"{hashlib.sha256(second).hexdigest()}\tsecond.bin\n",
        )
        result = self.run_with_manifest_removed_after_open(
            "config/vendor.sha256.tsv", vendor_args
        )
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertIn("vendor=2", result.stdout)
        self.assertFalse((self.repo / "config" / "vendor.sha256.tsv").exists())
        self.assertNotIn("vendor.sha256.tsv", self.combined(result))

        private_missing = "config/PRIVATE_MISSING_MANIFEST.tsv"
        result = self.run_guard("--pairs", private_missing)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(private_missing, self.combined(result))

    def test_fixed_temp_parent_defeats_caller_ancestor_substitution(self) -> None:
        args = self.seed_pair(b"same", b"same")
        temp_area = self.repo / "temp-ancestor"
        base = temp_area / "base"
        moved = temp_area / "moved"
        victim = temp_area / "victim"
        base.mkdir(parents=True)
        victim.mkdir()
        sentinel = victim / "must-survive.txt"
        sentinel.write_text("synthetic sentinel\n", encoding="utf-8")

        actual_cmp = shutil.which("cmp")
        self.assertIsNotNone(actual_cmp)
        shim_dir = self.repo / "ancestor-shim"
        shim_dir.mkdir()
        shim = shim_dir / "cmp"
        marker = temp_area / "triggered"
        shim.write_text(
            "#!/bin/sh\n"
            f"if [ ! -e '{marker}' ]; then\n"
            f"  : > '{marker}'\n"
            f"  mv '{base}' '{moved}'\n"
            f"  ln -s '{victim}' '{base}'\n"
            "fi\n"
            f"exec '{actual_cmp}' \"$@\"\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        result = self.run_guard(
            *args,
            env_extra={
                "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "TMPDIR": str(base),
            },
        )
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertTrue(sentinel.is_file())
        self.assertTrue(base.is_symlink())
        self.assertFalse(any(moved.glob("release-parity.*")))

    def test_manifest_retention_has_no_platform_fd_path_dependency(self) -> None:
        source_text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("/proc/self/fd", source_text)
        self.assertNotIn("/dev/fd", source_text)
        self.assertNotIn("fd_reference", source_text)
        for needle in (
            'exec 7< "$pairs_manifest"',
            'done <&7',
            'exec 7<&-',
            'exec 8< "$vendor_manifest"',
            'done <&8',
            'exec 8<&-',
        ):
            with self.subTest(single_open_read_close=needle):
                self.assertEqual(source_text.count(needle), 1)
        pair_check = 'is_plain_file "$pairs_manifest"'
        vendor_check = 'is_plain_file "$vendor_manifest"'
        pair_checks = [
            match.start() for match in re.finditer(re.escape(pair_check), source_text)
        ]
        vendor_checks = [
            match.start() for match in re.finditer(re.escape(vendor_check), source_text)
        ]
        self.assertEqual(len(pair_checks), 2)
        self.assertEqual(len(vendor_checks), 2)
        pair_open = source_text.index('exec 7< "$pairs_manifest"')
        pair_read = source_text.index('done <&7')
        pair_close = source_text.index('exec 7<&-')
        self.assertLess(pair_checks[0], pair_open)
        self.assertLess(pair_open, pair_checks[1])
        self.assertLess(pair_checks[1], pair_read)
        self.assertLess(pair_read, pair_close)
        vendor_open = source_text.index('exec 8< "$vendor_manifest"')
        vendor_read = source_text.index('done <&8')
        vendor_close = source_text.index('exec 8<&-')
        self.assertLess(vendor_checks[0], vendor_open)
        self.assertLess(vendor_open, vendor_checks[1])
        self.assertLess(vendor_checks[1], vendor_read)
        self.assertLess(vendor_read, vendor_close)

        conventions = (
            ROOT / "template" / "docs" / "ENGINEERING_CONVENTIONS.md"
        ).read_text(encoding="utf-8")
        self.assertIn("trusted, quiescent checkout", conventions)
        self.assertIn("concurrent same-user replacement", conventions)
        self.assertRegex(conventions, r"FIFO\s+substitution can also block")
        self.assertIn("Do not mutate release inputs concurrently", conventions)
        self.assertIn("pipeline's ordinary job timeout", conventions)
        self.assertIn("hostile shared workspace", conventions)
        self.assertIn("platform sandbox or identity-verifying helper", conventions)

        anatomy = (ROOT / "docs" / "ANATOMY.md").read_text(encoding="utf-8")
        self.assertIn("trusted quiescent checkout", anatomy)
        self.assertIn(
            "Concurrent same-user manifest replacement is explicitly outside",
            anatomy,
        )
        self.assertIn("FIFO substitution can block", anatomy)
        self.assertIn("keep the pipeline timeout", anatomy)
        self.assertIn("hostile shared workspace", anatomy)
        self.assertIn("separate sandbox/helper", anatomy)
        lift_log = (ROOT / "docs" / "LIFT-LOG.md").read_text(encoding="utf-8")
        self.assertIn("trusted quiescent checkout", lift_log)
        self.assertIn("concurrent same-user manifest replacement", lift_log)
        self.assertIn("FIFO substitution", lift_log)
        self.assertIn("separate sandbox/helper", lift_log)
        self.assertIn("pipeline timeout", lift_log)

    def test_comparison_inventory_and_digest_checks_are_load_bearing(self) -> None:
        source_text = SCRIPT.read_text(encoding="utf-8")

        pair_args = self.seed_pair(b"source", b"release")
        pair_needle = (
            'if ! cmp -s "$source_path" "$release_path" >/dev/null 2>&1; then\n'
            "      record_violation\n"
            "    fi"
        )
        self.assertEqual(source_text.count(pair_needle), 1)
        pair_mutant = self.repo / "scripts" / "pair-mutant.sh"
        pair_mutant.write_text(
            source_text.replace(pair_needle, ": # mutation: comparison disabled"),
            encoding="utf-8",
        )
        pair_mutant.chmod(0o755)
        self.assertEqual(self.run_guard(*pair_args).returncode, 1)
        self.assertEqual(self.run_guard(*pair_args, script=pair_mutant).returncode, 0)

        shutil.rmtree(self.repo / "assets")
        shutil.rmtree(self.repo / "dist")
        vendor_args = self.seed_vendor()
        self.write_bytes("dist/vendor/unlisted.bin", b"extra")
        inventory_needle = (
            'cmp -s "$vendor_sorted" "$release_sorted" >/dev/null 2>&1 '
            "|| record_violation"
        )
        self.assertEqual(source_text.count(inventory_needle), 1)
        inventory_mutant = self.repo / "scripts" / "inventory-mutant.sh"
        inventory_mutant.write_text(
            source_text.replace(
                inventory_needle, ": # mutation: extra release files ignored"
            ),
            encoding="utf-8",
        )
        inventory_mutant.chmod(0o755)
        self.assertEqual(self.run_guard(*vendor_args).returncode, 1)
        self.assertEqual(
            self.run_guard(*vendor_args, script=inventory_mutant).returncode, 0
        )

        (self.repo / "dist" / "vendor" / "unlisted.bin").unlink()
        self.write_bytes("vendor/source/unlisted.bin", b"extra")
        source_inventory_needle = (
            'cmp -s "$vendor_sorted" "$source_sorted" >/dev/null 2>&1 '
            "|| record_violation"
        )
        self.assertEqual(source_text.count(source_inventory_needle), 1)
        source_inventory_mutant = self.repo / "scripts" / "source-inventory-mutant.sh"
        source_inventory_mutant.write_text(
            source_text.replace(
                source_inventory_needle,
                ": # mutation: extra source files ignored",
            ),
            encoding="utf-8",
        )
        source_inventory_mutant.chmod(0o755)
        self.assertEqual(self.run_guard(*vendor_args).returncode, 1)
        self.assertEqual(
            self.run_guard(*vendor_args, script=source_inventory_mutant).returncode,
            0,
        )

        (self.repo / "vendor" / "source" / "unlisted.bin").unlink()
        self.write_bytes("dist/vendor/nested/library.bin", b"release drift")
        vendor_byte_needle = (
            'cmp -s "$source_file" "$release_file" >/dev/null 2>&1 '
            "|| record_violation"
        )
        self.assertEqual(source_text.count(vendor_byte_needle), 1)
        vendor_byte_mutant = self.repo / "scripts" / "vendor-byte-mutant.sh"
        vendor_byte_mutant.write_text(
            source_text.replace(
                vendor_byte_needle,
                ": # mutation: vendor byte comparison disabled",
            ),
            encoding="utf-8",
        )
        vendor_byte_mutant.chmod(0o755)
        self.assertEqual(self.run_guard(*vendor_args).returncode, 1)
        self.assertEqual(
            self.run_guard(*vendor_args, script=vendor_byte_mutant).returncode,
            0,
        )

        self.write_bytes(
            "dist/vendor/nested/library.bin", b"synthetic vendor bytes\x00\n"
        )
        self.write_text(
            "config/vendor.sha256.tsv",
            f"{'0' * 64}\tnested/library.bin\n",
        )
        digest_needle = (
            '[ "$actual_digest" = "$expected_digest" ] || record_violation'
        )
        self.assertEqual(source_text.count(digest_needle), 1)
        digest_mutant = self.repo / "scripts" / "digest-mutant.sh"
        digest_mutant.write_text(
            source_text.replace(
                digest_needle, ": # mutation: declared digest trusted"
            ),
            encoding="utf-8",
        )
        digest_mutant.chmod(0o755)
        self.assertEqual(self.run_guard(*vendor_args).returncode, 1)
        self.assertEqual(
            self.run_guard(*vendor_args, script=digest_mutant).returncode, 0
        )


class ReleaseParityGeneratorTests(unittest.TestCase):
    def test_every_stack_stamps_the_executable_guard_and_convention(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for answers in sorted((ROOT / "examples").glob("*.answers.json")):
                with self.subTest(answers=answers.name):
                    output = Path(temp) / answers.stem
                    subprocess.run(
                        [
                            "python3",
                            str(ROOT / "bin" / "generate.py"),
                            "--values",
                            str(answers),
                            "--output",
                            str(output),
                        ],
                        cwd=ROOT,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    script = output / "scripts" / "verify-release-parity.sh"
                    self.assertTrue(script.is_file(), answers.name)
                    self.assertTrue(os.access(script, os.X_OK), answers.name)
                    self.assertNotIn("{{", script.read_text(encoding="utf-8"))
                    makefile = (output / "Makefile").read_text(encoding="utf-8")
                    self.assertIn("release-parity:", makefile, answers.name)
                    self.assertIn(
                        "export RELEASE_PARITY_PAIRS RELEASE_VENDOR_MANIFEST",
                        makefile,
                    )
                    self.assertIn(
                        "override RELEASE_PARITY_PAIRS := "
                        "$(value RELEASE_PARITY_PAIRS)",
                        makefile,
                    )
                    self.assertIn(
                        "bash scripts/verify-release-parity.sh --from-env",
                        makefile,
                    )

                    source = output / "release source.bin"
                    release = output / "release output.bin"
                    manifest = output / "config" / "release pairs.tsv"
                    source.write_bytes(b"synthetic release bytes")
                    release.write_bytes(b"synthetic release bytes")
                    manifest.parent.mkdir(parents=True, exist_ok=True)
                    manifest.write_text(
                        "release source.bin\trelease output.bin\n",
                        encoding="utf-8",
                    )
                    make = shutil.which("make")
                    self.assertIsNotNone(make)
                    passed = subprocess.run(
                        [
                            make,
                            "release-parity",
                            "RELEASE_PARITY_PAIRS=config/release pairs.tsv",
                        ],
                        cwd=output,
                        check=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    self.assertEqual(
                        passed.returncode,
                        0,
                        f"{answers.name}: {passed.stdout}{passed.stderr}",
                    )
                    raw_make_values = (
                        (
                            "config/literal $(shell touch MAKE_PAREN_EXECUTED).tsv",
                            "MAKE_PAREN_EXECUTED",
                        ),
                        (
                            "config/literal ${shell touch MAKE_BRACE_EXECUTED}.tsv",
                            "MAKE_BRACE_EXECUTED",
                        ),
                        ("config/literal cash$money.tsv", "MAKE_DOLLAR_EXECUTED"),
                    )
                    for raw_path, marker_name in raw_make_values:
                        with self.subTest(answers=answers.name, raw_path=raw_path):
                            raw_manifest = output / raw_path
                            raw_manifest.write_text(
                                "release source.bin\trelease output.bin\n",
                                encoding="utf-8",
                            )
                            marker = output / marker_name
                            literal = subprocess.run(
                                [
                                    make,
                                    "release-parity",
                                    f"RELEASE_PARITY_PAIRS={raw_path}",
                                ],
                                cwd=output,
                                check=False,
                                text=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                            )
                            self.assertEqual(
                                literal.returncode,
                                0,
                                f"{answers.name}: {literal.stdout}{literal.stderr}",
                            )
                            self.assertFalse(marker.exists(), marker_name)
                    for malicious in (
                        "missing.tsv; true",
                        "missing.tsv || true",
                        "   ",
                    ):
                        with self.subTest(answers=answers.name, malicious=malicious):
                            rejected = subprocess.run(
                                [
                                    make,
                                    "release-parity",
                                    f"RELEASE_PARITY_PAIRS={malicious}",
                                ],
                                cwd=output,
                                check=False,
                                text=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                            )
                            self.assertNotEqual(rejected.returncode, 0)
                    conventions = (
                        output / "docs" / "ENGINEERING_CONVENTIONS.md"
                    ).read_text(encoding="utf-8")
                    agents = (output / "AGENTS.md").read_text(encoding="utf-8")
                    claude = (output / "CLAUDE.md").read_text(encoding="utf-8")
                    self.assertEqual(
                        conventions.count(
                            "## 8. Adopt canonical process code with a parity lock"
                        ),
                        1,
                        answers.name,
                    )
                    self.assertIn(
                        "## Adopt canonical process code with parity evidence",
                        agents,
                    )
                    self.assertIn("scripts/verify-release-parity.sh", agents)
                    self.assertIn(
                        "reversible canonical adoption with golden/release parity",
                        claude,
                    )


if __name__ == "__main__":
    unittest.main()
