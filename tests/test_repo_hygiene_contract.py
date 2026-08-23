"""Adversarial contract for the offline repository-hygiene tripwire."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "repo-hygiene.sh"
HOOK = ROOT / "template" / ".githooks" / "pre-commit"
BASH = os.environ.get("REPO_HYGIENE_BASH", "bash")


class RepoHygieneContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic Test")
        self.git("config", "user.email", "synthetic@example.com")

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def write(self, relative: str, content: str | bytes) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def commit_all(self, message: str = "test: synthetic fixture") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def run_hygiene(
        self,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            cwd=cwd or self.repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "LC_ALL": "C", **(env or {})},
        )

    @staticmethod
    def combined(result: subprocess.CompletedProcess[str]) -> str:
        return result.stdout + result.stderr

    def seed_safe_index(self) -> None:
        self.write(
            "README.md",
            (
                "Synthetic contacts: dev@example.com, qa@sample.test, "
                "ops@fixture.invalid\n"
                "Machine transport: git@github.com:synthetic/repository.git\n"
                "Requires the repository secret named SYNTHETIC_API_KEY.\n"
                "password = decodeURIComponent(url.password)\n"
                "DATABASE_URL=postgresql://postgres:postgres@postgres:5432/app\n"
                'API_KEY: "CHANGE_ME_LONG_RANDOM"\n'
                "CALLBACK=https://user:secret@example.test/path\n"
            ),
        )
        self.git("add", "README.md")

    def git_race_environment(self, mode: str, **values: str) -> dict[str, str]:
        shim_dir = Path(self.tempdir.name) / f"git-shim-{mode}"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(
            """#!/bin/sh
if [ "${RACE_MODE:-}" = index ] && [ "${1:-}" = ls-files ]; then
  "$REAL_GIT" "$@"
  status=$?
  GIT_INDEX_FILE="$RACE_ACTUAL_INDEX" "$REAL_GIT" update-index --add \\
    --cacheinfo "100644,$RACE_BLOB,race-marker.txt" >/dev/null 2>&1 || exit 91
  exit "$status"
fi
if [ "${RACE_MODE:-}" = refs ] && [ "${1:-}" = rev-list ]; then
  "$REAL_GIT" "$@"
  status=$?
  "$REAL_GIT" update-ref refs/tags/race-ref "$RACE_COMMIT" \\
    >/dev/null 2>&1 || exit 92
  exit "$status"
fi
if [ "${RACE_MODE:-}" = signal ] && [ "${1:-}" = ls-files ]; then
  "$REAL_GIT" "$@"
  status=$?
  kill -TERM "$PPID"
  exit "$status"
fi
exec "$REAL_GIT" "$@"
""",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        return {
            "PATH": str(shim_dir) + os.pathsep + os.environ["PATH"],
            "REAL_GIT": shutil.which("git", path=os.environ["PATH"]) or "git",
            "RACE_MODE": mode,
            **values,
        }

    def test_clean_index_allows_synthetic_email_binary_odd_name_and_symlink(self) -> None:
        self.seed_safe_index()
        self.write("assets/opaque.bin", b"\x00safe-binary\xff")
        self.write("odd\nname.txt", "safe odd filename\n")
        outside = Path(self.tempdir.name) / "outside.txt"
        outside.write_text(("123" + "-45-" + "6789"), encoding="utf-8")
        os.symlink(outside, self.repo / "outside-link.txt")
        self.git("add", "-A")

        for args in ((), ("--staged",)):
            with self.subTest(args=args):
                result = self.run_hygiene(*args)
                self.assertEqual(result.returncode, 0, self.combined(result))
                self.assertIn("repo-hygiene: PASS scope=index", result.stdout)
                self.assertNotIn(str(outside), self.combined(result))

    def test_clean_unborn_repository_passes(self) -> None:
        result = self.run_hygiene("--staged")
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertIn("repo-hygiene: PASS scope=index", result.stdout)

    def test_forbidden_paths_fail_without_disclosing_paths(self) -> None:
        self.seed_safe_index()
        forbidden_paths = (
            ".env",
            ".envrc",
            "git-crypt-production.key",
            "build/output.bin",
            "out/output.bin",
            "dist/private-bundle.js",
            "htmlcov/index.html",
            ".turbo/cache",
            ".pnpm-store/cache",
            ".ruff_cache/cache",
            ".mutation-check.lock/original",
            "venv/bin/activate",
            "package.egg-info/PKG-INFO",
            ".coverage",
            ".idea/workspace.xml",
            ".vscode/settings.json",
            ".docker-data/state",
            ".secret-vault/backup",
            ".deploy/private-config",
            ".kube/config",
            "cluster.kubeconfig",
            "terraform.tfstate",
            "debug.log",
            ".claude/settings.local.json",
            ".claude/worktrees/state",
            ".direnv/cache",
            ".terraform/state",
        )
        for relative in forbidden_paths:
            self.write(relative, "safe content\n")
        near_misses = (
            "builder/output.bin",
            "output/result.bin",
            ".vscode-example/settings.json",
            "git-crypt-key.txt",
            "debug.log.example",
            "venv-example/bin/activate",
            "package.egg-info.txt",
            ".coverage.example",
            ".mutation-check.lock.example/original",
        )
        for relative in near_misses:
            self.write(relative, "safe content\n")
        self.git("add", "-A", "--force")

        result = self.run_hygiene("--staged")
        output = self.combined(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn(
            f"rule=forbidden-path hits={len(forbidden_paths)}", output
        )
        for relative in forbidden_paths:
            self.assertNotIn(relative, output)
        for relative in near_misses:
            self.assertNotIn(relative, output)

    def test_secret_and_pii_rules_report_names_not_values_or_paths(self) -> None:
        self.seed_safe_index()
        token = "api_key=" + "B" * 24
        synthetic_word_bypass = "api_key=live-" + "test-" + "R8" * 12
        punctuated_password = 'password="correct!horse%battery&staple"'
        placeholder_mutation = 'api_key="CHANGE_ME_LONG_RANDOM_X"'
        ssn = "123" + "-45-" + "6789"
        email = "person" + "@" + "private-fixture" + ".localhost"
        account = "account: " + "9" * 12
        address = "742" + " Evergreen Road"
        url = "https://operator:" + "Q7m9" * 6 + "@service.localhost/api"
        tutorial_host_mutation = "https://user:secret@service.localhost/path"
        encrypted_key = "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"
        pgp_key = "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"
        self.write(
            "notes-sensitive.txt",
            "\n".join(
                (
                    token,
                    synthetic_word_bypass,
                    punctuated_password,
                    placeholder_mutation,
                    ssn,
                    email,
                    account,
                    address,
                    url,
                    tutorial_host_mutation,
                    encrypted_key,
                    pgp_key,
                )
            ),
        )
        self.git("add", "-A")

        result = self.run_hygiene("--staged")
        output = self.combined(result)
        self.assertEqual(result.returncode, 1, output)
        for rule in (
            "credential-assignment",
            "pii-ssn",
            "non-synthetic-email",
            "pii-labelled-account-number",
            "pii-street-address",
            "credentialed-url",
            "private-key-header",
        ):
            self.assertIn(f"rule={rule}", output)
        for forbidden in (
            token,
            synthetic_word_bypass,
            punctuated_password,
            placeholder_mutation,
            ssn,
            email,
            account,
            address,
            url,
            tutorial_host_mutation,
            encrypted_key,
            pgp_key,
            "notes-sensitive.txt",
        ):
            self.assertNotIn(forbidden, output)

    def test_each_credential_and_private_key_mutation_fails_independently(self) -> None:
        fixtures = (
            ("credential-assignment", "api_key=" + "T" * 24),
            ("credential-assignment", "api_key=live-" + "test-" + "U8" * 12),
            ("credential-assignment", 'password="correct!horse%battery&staple"'),
            ("credential-assignment", 'api_key="CHANGE_ME_LONG_RANDOM_X"'),
            (
                "credentialed-url",
                "https://operator:" + "V7m9" * 6 + "@service.localhost/api",
            ),
            ("credentialed-url", "https://user:secret@service.localhost/path"),
            (
                "credentialed-url",
                "postgresql://operator:%25EncodedValue123456@service.localhost/db",
            ),
            ("private-key-header", "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"),
            ("private-key-header", "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"),
            ("private-key-header", "-----BEGIN " + "DSA PRIVATE KEY-----"),
        )
        self.seed_safe_index()
        for expected_rule, fixture in fixtures:
            with self.subTest(expected_rule=expected_rule, fixture=fixture[:20]):
                path = self.write("isolated-mutation.txt", fixture + "\n")
                self.git("add", "isolated-mutation.txt")
                result = self.run_hygiene("--staged")
                output = self.combined(result)
                self.assertEqual(result.returncode, 1, output)
                self.assertIn(f"rule={expected_rule} hits=1", output)
                self.assertNotIn(fixture, output)
                self.assertNotIn("isolated-mutation.txt", output)
                self.git("reset", "-q", "isolated-mutation.txt")
                path.unlink()

    def test_machine_email_names_require_synthetic_domains_or_transport_context(self) -> None:
        fixtures = (
            "git@private-fixture.localhost",
            "git@private-fixture.localhost:",
            "git@private-fixture.localhost: escalation",
            "notgit@private-fixture.localhost:owner/repository",
            "noreply@private-fixture.localhost",
            "no-reply@private-fixture.localhost",
        )
        self.seed_safe_index()
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                path = self.write("isolated-email.txt", fixture + "\n")
                self.git("add", "isolated-email.txt")
                result = self.run_hygiene("--staged")
                output = self.combined(result)
                self.assertEqual(result.returncode, 1, output)
                self.assertIn("rule=non-synthetic-email hits=1", output)
                self.assertNotIn(fixture, output)
                self.assertNotIn("isolated-email.txt", output)
                self.git("reset", "-q", "isolated-email.txt")
                path.unlink()

    def test_staged_scope_reads_index_not_unstaged_worktree(self) -> None:
        self.write("tracked.txt", "safe\n")
        self.commit_all()
        token = "api_key=" + "C" * 24
        self.write("tracked.txt", token + "\n")

        unstaged = self.run_hygiene("--staged")
        self.assertEqual(unstaged.returncode, 0, self.combined(unstaged))

        self.git("add", "tracked.txt")
        self.write("tracked.txt", "safe in working tree again\n")
        staged = self.run_hygiene("--staged")
        self.assertEqual(staged.returncode, 1, self.combined(staged))
        self.assertIn("rule=credential-assignment", self.combined(staged))
        self.assertNotIn(token, self.combined(staged))

    def test_staged_deletion_does_not_read_removed_worktree_content(self) -> None:
        self.write("removed.txt", "safe\n")
        self.commit_all()
        self.git("rm", "-q", "removed.txt")
        result = self.run_hygiene("--staged")
        self.assertEqual(result.returncode, 0, self.combined(result))

    def test_ascii_credential_in_binary_and_oversized_blob_fail_closed(self) -> None:
        self.seed_safe_index()
        token = "api_key=" + "E" * 24
        self.write("assets/binary.dat", b"\x00prefix\x00" + token.encode() + b"\xff")
        self.git("add", "-A")
        binary = self.run_hygiene("--staged")
        binary_output = self.combined(binary)
        self.assertEqual(binary.returncode, 1, binary_output)
        self.assertIn("rule=credential-assignment", binary_output)
        self.assertNotIn(token, binary_output)
        self.assertNotIn("binary.dat", binary_output)

        self.git("reset", "-q", "assets/binary.dat")
        (self.repo / "assets/binary.dat").unlink()
        self.write("assets/large.dat", b"x" * (4_194_304 + 1))
        self.git("add", "-A")
        oversized = self.run_hygiene("--staged")
        oversized_output = self.combined(oversized)
        self.assertEqual(oversized.returncode, 1, oversized_output)
        self.assertIn("rule=oversized-blob", oversized_output)
        self.assertNotIn("large.dat", oversized_output)

    def test_history_finds_removed_content_and_path_without_identifiers(self) -> None:
        self.write("README.md", "safe\n")
        base_commit = self.commit_all()
        token = "api_key=" + "D" * 24
        email = "historical" + "@" + "archive-fixture" + ".localhost"
        self.write("dist/old-private.js", token + "\n" + email + "\n")
        exposed_commit = self.commit_all("COMMIT-CANARY synthetic exposure")
        self.git("update-ref", "refs/remotes/origin/restricted-archive", exposed_commit)
        self.git("reset", "-q", "--hard", base_commit)

        current = self.run_hygiene("--staged")
        self.assertEqual(current.returncode, 0, self.combined(current))

        history = self.run_hygiene("--history")
        output = self.combined(history)
        self.assertEqual(history.returncode, 1, output)
        self.assertIn("rule=historical-credential-assignment", output)
        self.assertIn("rule=historical-forbidden-path", output)
        self.assertIn("rule=historical-non-synthetic-email", output)
        for forbidden in (
            token,
            email,
            "old-private.js",
            "restricted-archive",
            "COMMIT-CANARY",
            exposed_commit,
        ):
            self.assertNotIn(forbidden, output)

    def test_unreachable_dangling_exposure_is_not_history_scope(self) -> None:
        self.write("README.md", "safe\n")
        base_commit = self.commit_all()
        token = "api_key=" + "F" * 24
        self.write("dangling.txt", token + "\n")
        self.commit_all("test: unreachable synthetic object")
        self.git("reset", "-q", "--hard", base_commit)
        result = self.run_hygiene("--history")
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertNotIn(token, self.combined(result))

    def test_history_includes_detached_head_and_direct_blob_ref(self) -> None:
        self.write("README.md", "safe\n")
        base_commit = self.commit_all()
        initial_branch = self.git("branch", "--show-current").stdout.strip()
        token = "api_key=" + "G" * 24
        self.write("detached.txt", token + "\n")
        detached_commit = self.commit_all("test: detached synthetic object")
        self.git("checkout", "-q", "--detach", detached_commit)
        self.git("branch", "-f", initial_branch, base_commit)
        self.git("read-tree", base_commit)

        detached = self.run_hygiene("--history")
        self.assertEqual(detached.returncode, 1, self.combined(detached))
        self.assertIn("rule=historical-credential-assignment", self.combined(detached))
        self.assertNotIn(detached_commit, self.combined(detached))
        self.assertNotIn(token, self.combined(detached))

        self.git("checkout", "-q", "-f", initial_branch)
        blob_token = "api_key=" + "H" * 24
        blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=self.repo,
            input=blob_token + "\n",
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        self.git("update-ref", "refs/tags/synthetic-blob", blob)
        direct_blob = self.run_hygiene("--history")
        self.assertEqual(direct_blob.returncode, 1, self.combined(direct_blob))
        self.assertIn(
            "rule=historical-credential-assignment", self.combined(direct_blob)
        )
        for forbidden in (blob, blob_token, "synthetic-blob"):
            self.assertNotIn(forbidden, self.combined(direct_blob))

    def test_index_flags_do_not_hide_a_staged_credential(self) -> None:
        token = "api_key=" + "J" * 24
        self.write("flagged.txt", token + "\n")
        self.commit_all()

        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", "--no-assume-unchanged", "flagged.txt")
                self.git("update-index", "--no-skip-worktree", "flagged.txt")
                self.git("update-index", flag, "flagged.txt")
                result = self.run_hygiene("--staged")
                self.assertEqual(result.returncode, 1, self.combined(result))
                self.assertIn("rule=credential-assignment", self.combined(result))
                self.assertNotIn(token, self.combined(result))
                self.assertNotIn("flagged.txt", self.combined(result))

    def test_git_replacement_refs_cannot_hide_index_or_history(self) -> None:
        self.write("README.md", "safe\n")
        base_commit = self.commit_all()
        token = "api_key=" + "M" * 24
        self.write("replaced.txt", token + "\n")
        self.git("add", "replaced.txt")
        exposed_blob = self.git("hash-object", "replaced.txt").stdout.strip()
        safe_blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=self.repo,
            input="safe replacement\n",
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        self.git("replace", exposed_blob, safe_blob)

        staged = self.run_hygiene("--staged")
        self.assertEqual(staged.returncode, 1, self.combined(staged))
        self.assertIn("rule=credential-assignment", self.combined(staged))

        self.git("commit", "-q", "-m", "test: replacement-resistant fixture")
        exposed_commit_id = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("update-ref", "refs/remotes/origin/replacement-proof", exposed_commit_id)
        self.git("reset", "-q", "--hard", base_commit)
        history = self.run_hygiene("--history")
        self.assertEqual(history.returncode, 1, self.combined(history))
        self.assertIn("rule=historical-credential-assignment", self.combined(history))
        for output in (self.combined(staged), self.combined(history)):
            for forbidden in (
                token,
                exposed_blob,
                safe_blob,
                exposed_commit_id,
                "replaced.txt",
                "replacement-proof",
            ):
                self.assertNotIn(forbidden, output)

    def test_unmerged_index_fails_closed_without_content_or_path(self) -> None:
        self.write("conflict.txt", "base\n")
        self.commit_all()
        initial_branch = self.git("branch", "--show-current").stdout.strip()
        self.git("checkout", "-q", "-b", "synthetic-other")
        self.write("conflict.txt", "other-side-private-marker\n")
        self.commit_all()
        self.git("checkout", "-q", initial_branch)
        self.write("conflict.txt", "current-side-private-marker\n")
        self.commit_all()
        self.git("merge", "synthetic-other", check=False)

        result = self.run_hygiene("--staged")
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=unmerged-index", output)
        for forbidden in (
            "conflict.txt",
            "other-side-private-marker",
            "current-side-private-marker",
        ):
            self.assertNotIn(forbidden, output)

    def test_missing_index_object_fails_closed_without_lazy_recovery(self) -> None:
        token = "api_key=" + "K" * 24
        self.write("missing-object.txt", token + "\n")
        self.commit_all()
        blob = self.git("rev-parse", "HEAD:missing-object.txt").stdout.strip()
        object_path = self.repo / ".git" / "objects" / blob[:2] / blob[2:]
        object_path.unlink()

        result = self.run_hygiene("--staged")
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=missing-object", output)
        for forbidden in (token, blob, "missing-object.txt"):
            self.assertNotIn(forbidden, output)

    def test_promisor_missing_object_never_invokes_remote_helper(self) -> None:
        token = "api_key=" + "P" * 24
        self.write("promisor.txt", token + "\n")
        self.commit_all()
        blob = self.git("rev-parse", "HEAD:promisor.txt").stdout.strip()
        object_path = self.repo / ".git" / "objects" / blob[:2] / blob[2:]
        object_path.unlink()

        canary = Path(self.tempdir.name) / "promisor-canary"
        helper = Path(self.tempdir.name) / "promisor-helper"
        helper.write_text(
            '#!/bin/sh\nprintf invoked > "$PROMISOR_CANARY"\nexit 1\n',
            encoding="utf-8",
        )
        helper.chmod(0o755)
        self.git("config", "extensions.partialClone", "origin")
        self.git("config", "remote.origin.promisor", "true")
        self.git("config", "remote.origin.partialclonefilter", "blob:none")
        self.git("config", "protocol.ext.allow", "always")
        self.git("config", "remote.origin.url", f"ext::{helper}")

        probe_env = {**os.environ, "PROMISOR_CANARY": str(canary)}
        probe_env.pop("GIT_NO_LAZY_FETCH", None)
        subprocess.run(
            ["git", "cat-file", "-t", blob],
            cwd=self.repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=probe_env,
        )
        self.assertTrue(canary.exists(), "promisor canary must be a valid positive control")
        canary.unlink()

        result = self.run_hygiene(
            "--staged", env={"PROMISOR_CANARY": str(canary)}
        )
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=missing-object", output)
        self.assertFalse(canary.exists())
        for forbidden in (token, blob, "promisor.txt", str(helper), str(canary)):
            self.assertNotIn(forbidden, output)

    def test_network_and_host_sdk_path_canaries_are_never_invoked(self) -> None:
        self.seed_safe_index()
        shim_dir = Path(self.tempdir.name) / "command-canaries"
        shim_dir.mkdir()
        canary = Path(self.tempdir.name) / "command-canary"
        for command in ("curl", "wget", "python", "python3", "node", "npm", "npx"):
            shim = shim_dir / command
            shim.write_text(
                '#!/bin/sh\nprintf invoked >> "$COMMAND_CANARY"\nexit 97\n',
                encoding="utf-8",
            )
            shim.chmod(0o755)

        result = self.run_hygiene(
            "--staged",
            env={
                "COMMAND_CANARY": str(canary),
                "PATH": str(shim_dir) + os.pathsep + os.environ["PATH"],
            },
        )
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertFalse(canary.exists())

    def test_index_change_during_scan_fails_closed(self) -> None:
        self.seed_safe_index()
        self.git("add", "-A")
        race_blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=self.repo,
            input="safe race object\n",
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        env = self.git_race_environment(
            "index",
            RACE_ACTUAL_INDEX=str(self.repo / ".git" / "index"),
            RACE_BLOB=race_blob,
        )

        result = self.run_hygiene("--staged", env=env)
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=index-changed-during-scan", output)
        for forbidden in (race_blob, "race-marker.txt", str(self.repo)):
            self.assertNotIn(forbidden, output)

    def test_ref_change_during_history_scan_fails_closed(self) -> None:
        self.write("README.md", "safe\n")
        base_commit = self.commit_all()
        env = self.git_race_environment("refs", RACE_COMMIT=base_commit)

        result = self.run_hygiene("--history", env=env)
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=refs-changed-during-scan", output)
        for forbidden in (base_commit, "race-ref", str(self.repo)):
            self.assertNotIn(forbidden, output)

    def test_signal_during_scan_exits_without_pass_or_disclosure(self) -> None:
        self.seed_safe_index()
        env = self.git_race_environment("signal")

        result = self.run_hygiene("--staged", env=env)
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertNotIn("PASS", output)
        self.assertNotIn(str(self.repo), output)

    def test_history_rejects_shallow_repository(self) -> None:
        token = "api_key=" + "N" * 24
        self.write("historical.txt", token + "\n")
        self.commit_all()
        self.write("historical.txt", "safe current content\n")
        self.commit_all()
        shallow_repo = Path(self.tempdir.name) / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", self.repo.as_uri(), shallow_repo],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        result = self.run_hygiene("--history", cwd=shallow_repo)
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=history-incomplete-shallow", output)
        for forbidden in (token, "historical.txt", str(shallow_repo)):
            self.assertNotIn(forbidden, output)

    def test_cleanup_failure_suppresses_private_temp_path(self) -> None:
        shim_dir = Path(self.tempdir.name) / "shim"
        shim_dir.mkdir()
        rm_shim = shim_dir / "rm"
        rm_shim.write_text(
            '#!/bin/sh\necho "PRIVATE-TEMP-CANARY $*"\nexit 1\n',
            encoding="utf-8",
        )
        rm_shim.chmod(0o755)

        result = self.run_hygiene(
            "--staged",
            env={"PATH": str(shim_dir) + os.pathsep + os.environ["PATH"]},
        )
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=private-temp-cleanup", output)
        self.assertNotIn("PRIVATE-TEMP-CANARY", output)
        self.assertNotIn("repo-hygiene.", output)
        self.assertNotIn(str(self.repo), output)

    def test_precommit_runs_hygiene_for_docs_and_full_gates_for_source(self) -> None:
        script = self.write("scripts/repo-hygiene.sh", SCRIPT.read_bytes())
        script.chmod(0o755)
        hook = self.write(".githooks/pre-commit", HOOK.read_bytes())
        hook.chmod(0o755)
        self.write(
            "Makefile",
            (
                "repo-hygiene:\n"
                "\tbash scripts/repo-hygiene.sh --staged\n"
                "precommit:\n"
                "\t@echo SOURCE-GATES-CANARY\n"
            ),
        )
        self.commit_all()

        self.write("docs/safe.md", "safe docs-only change\n")
        self.git("add", "docs/safe.md")
        docs = subprocess.run(
            ["sh", str(hook)],
            cwd=self.repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(docs.returncode, 0, self.combined(docs))
        self.assertIn("repo-hygiene: PASS scope=index", self.combined(docs))
        self.assertNotIn("SOURCE-GATES-CANARY", self.combined(docs))
        self.commit_all()

        self.write("src/code.js", "safe source change\n")
        self.git("add", "src/code.js")
        source = subprocess.run(
            ["sh", str(hook)],
            cwd=self.repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(source.returncode, 0, self.combined(source))
        self.assertIn("SOURCE-GATES-CANARY", self.combined(source))
        self.commit_all()

        token = "api_key=" + "S" * 24
        self.write("docs/sensitive.md", token + "\n")
        self.git("add", "docs/sensitive.md")
        rejected = subprocess.run(
            ["sh", str(hook)],
            cwd=self.repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output = self.combined(rejected)
        self.assertEqual(rejected.returncode, 2, output)
        self.assertIn("rule=credential-assignment", output)
        self.assertNotIn("SOURCE-GATES-CANARY", output)
        self.assertNotIn(token, output)
        self.assertNotIn("sensitive.md", output)

    def test_env_examples_are_allowed_but_real_env_variants_are_not(self) -> None:
        self.seed_safe_index()
        for name in (".env.example", ".env.sample", ".env.template"):
            self.write(name, "VALUE=placeholder\n")
        self.git("add", "-A")
        allowed = self.run_hygiene("--staged")
        self.assertEqual(allowed.returncode, 0, self.combined(allowed))

        self.write(".env.production", "VALUE=placeholder\n")
        self.git("add", "-f", ".env.production")
        denied = self.run_hygiene("--staged")
        self.assertEqual(denied.returncode, 1, self.combined(denied))
        self.assertIn("rule=forbidden-path", self.combined(denied))
        self.assertNotIn(".env.production", self.combined(denied))

    def test_invalid_invocation_and_non_repository_fail_closed(self) -> None:
        invalid = self.run_hygiene("--unknown")
        self.assertEqual(invalid.returncode, 2, self.combined(invalid))
        self.assertIn("usage:", invalid.stderr)
        self.assertNotIn("--unknown", self.combined(invalid))

        outside = Path(self.tempdir.name) / "not-a-repo"
        outside.mkdir()
        missing_repo = self.run_hygiene(cwd=outside)
        self.assertEqual(missing_repo.returncode, 2, self.combined(missing_repo))
        self.assertIn("code=not-a-git-repository", missing_repo.stderr)

    def test_source_is_dependency_light_content_suppressed_and_parses(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "curl ",
            "wget ",
            "/dev/tcp",
            "Invoke-WebRequest",
            "python ",
            "python3 ",
            "node ",
            "git fetch",
            "git pull",
            "git clone",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("fixed rule IDs and aggregate counts only", text)
        self.assertIn("GIT_NO_LAZY_FETCH=1", text)
        self.assertIn("GIT_NO_REPLACE_OBJECTS=1", text)
        self.assertIn("GIT_OPTIONAL_LOCKS=0", text)
        self.assertIn("GIT_TERMINAL_PROMPT=0", text)
        self.assertIn("GIT_INDEX_FILE", text)
        self.assertIn("git cat-file blob", text)
        self.assertIn("git for-each-ref", text)
        self.assertIn("set +x", text)
        syntax = subprocess.run(
            [BASH, "-n", str(SCRIPT)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(syntax.returncode, 0, self.combined(syntax))


if __name__ == "__main__":
    unittest.main()
