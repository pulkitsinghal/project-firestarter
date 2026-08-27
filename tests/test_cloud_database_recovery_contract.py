"""Contracts for the Supabase cloud snapshot/migration/restore-drill tooling."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "stacks" / "supabase-flutter"
SCRIPTS = STACK / "scripts"
GENERATOR = ROOT / "bin" / "generate.py"
BASH = os.environ.get("CLOUD_DB_RECOVERY_BASH", "bash")


def shell_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if os.name == "nt" and re.match(r"^[A-Za-z]:/", resolved):
        return f"/{resolved[0].lower()}{resolved[2:]}"
    return resolved


def run_script(
    script: Path,
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, str(script), *args],
        cwd=cwd or script.parent.parent,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )


def clean_cloud_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    for key in tuple(env):
        if key.startswith("CLOUD_DB_") or key.startswith("AWS_"):
            env.pop(key, None)
    return env


def configured_env(root: Path, fake_bin: Path) -> dict[str, str]:
    env = clean_cloud_env()
    env.update(
        {
            "PATH": os.pathsep.join((str(fake_bin), env.get("PATH", ""))),
            "CLOUD_DB_HOST": "example.invalid",
            "CLOUD_DB_PORT": "5432",
            "CLOUD_DB_NAME": "app",
            "CLOUD_DB_USER": "recovery",
            "CLOUD_DB_PASSWORD": "DB_SECRET_CANARY",
            "CLOUD_DB_TARGET_ID": "prod-opaque",
            "CLOUD_DB_CONNECTION_MODE": "session",
            "CLOUD_DB_ARCHIVE_ID": "archive-opaque",
            "CLOUD_DB_ARCHIVE_BUCKET": "BUCKET_CANARY",
            "CLOUD_DB_S3_PROVIDER": "Other",
            "CLOUD_DB_S3_ENDPOINT": "https://endpoint-canary.invalid",
            "CLOUD_DB_AUTHORIZATION_PUBLIC_KEY_FILE": "config/cloud-db-owner-public.pem",
            "CLOUD_DB_AUTHORIZATION_SIGNATURE": "U0lHTkFUVVJFX0NBTkFSWV9OT1RfQV9TRUFMX1NJR05BVFVSRV9DQU5BUllfTk9UX0FfUkVBTF9TSUdOQVRVUkU=",
            "AWS_ACCESS_KEY_ID": "ACCESS_KEY_CANARY",
            "AWS_SECRET_ACCESS_KEY": "SECRET_KEY_CANARY",
        }
    )
    return env


class CloudDatabaseRecoveryStaticContract(unittest.TestCase):
    def test_scripts_and_make_surface_are_stack_scoped(self) -> None:
        expected = {
            "cloud-db-lib.sh",
            "cloud-snapshot.sh",
            "cloud-migrate.sh",
            "cloud-restore.sh",
            "check-cloud-migration-sql.py",
        }
        self.assertTrue(expected <= {path.name for path in SCRIPTS.iterdir()})
        makefile = (STACK / "Makefile").read_text(encoding="utf-8")
        for target in (
            "cloud-snapshot:",
            "cloud-snapshot-prepare:",
            "cloud-snapshot-list:",
            "cloud-snapshot-execute:",
            "cloud-migrate:",
            "cloud-migrate-prepare:",
            "cloud-migrate-execute:",
            "cloud-restore:",
            "cloud-restore-prepare:",
            "cloud-restore-drill:",
        ):
            self.assertIn(target, makefile)

    def test_source_pattern_is_hardened_not_copied(self) -> None:
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in SCRIPTS.glob("cloud-*.sh"))
        for forbidden in (
            "PILGRIM",
            "R2_ACCOUNT_ID",
            "SKIP_PRE_SNAPSHOT",
            "--yes",
            "rclone/rclone:latest",
            "eval ",
        ):
            self.assertNotIn(forbidden, corpus)
        self.assertNotRegex(corpus, r"docker run[^\n]*-e [A-Z0-9_]+=\S")
        self.assertIn("transaction pooling is unsafe", corpus)
        self.assertIn("same-target/production restore is refused", corpus)
        self.assertNotIn("resolve_snapshot_target", corpus)
        self.assertIn("--immutable", corpus)
        self.assertIn("require_clean_source", corpus)
        self.assertIn("source_database_sha256", corpus)
        self.assertIn("destination_database_sha256", corpus)
        self.assertIn("--no-privileges", corpus)
        self.assertRegex(corpus, r'--exclude-extension=["\']\*["\']')
        self.assertIn("staged_migrations", corpus)
        self.assertNotIn("string_agg(version", corpus)
        self.assertIn("application-verification-required", corpus)
        self.assertNotIn("--clean", (SCRIPTS / "cloud-restore.sh").read_text(encoding="utf-8"))

    def test_authorization_and_transport_fail_closed(self) -> None:
        helper = (SCRIPTS / "cloud-db-lib.sh").read_text(encoding="utf-8")
        self.assertIn("firestarter-cloud-db-authorization-v1", helper)
        self.assertIn("authorization_id_sha256", helper)
        self.assertIn("authorization signature was not made by the committed owner key", helper)
        self.assertIn("URI options can override reviewed transport controls", helper)
        self.assertNotIn('--dbname="$CLOUD_DB_URL"', helper)
        self.assertIn('local -x PGPASSWORD="$CLOUD_DB_PASSWORD"', helper)
        self.assertIn('-e PGDATABASE', helper)
        self.assertIn('-e PGPASSWORD', helper)
        self.assertNotIn('-e CLOUD_DB_URL', helper)
        self.assertIn("must be an HTTPS endpoint", helper)
        self.assertIn("head -c", helper)
        self.assertIn("--retries 1 --low-level-retries 1", helper)
        self.assertIn("--cap-drop ALL --security-opt no-new-privileges", helper)
        self.assertIn("CLOUD_DB_SSLMODE must be verify-full", helper)
        self.assertIn("PGSSLROOTCERT", helper)

    def test_ready_marker_binds_archive_and_manifest(self) -> None:
        helper = (SCRIPTS / "cloud-db-lib.sh").read_text(encoding="utf-8")
        self.assertIn("archive_sha256=%s", helper)
        self.assertIn("manifest_sha256=%s", helper)
        self.assertIn("snapshot readiness marker is malformed", helper)
        self.assertIn("readiness marker is not bound to the downloaded manifest", helper)
        self.assertIn("uploaded readiness-marker proof", helper)
        self.assertIn("uploaded readiness marker checksum mismatch", helper)

    def test_tool_images_are_version_and_digest_pinned(self) -> None:
        helper = (SCRIPTS / "cloud-db-lib.sh").read_text(encoding="utf-8")
        self.assertRegex(
            helper,
            r'PG_CLIENT_IMAGE="postgres:[0-9.]+-alpine@sha256:[0-9a-f]{64}"',
        )
        self.assertRegex(
            helper,
            r'RCLONE_IMAGE="rclone/rclone:[0-9.]+@sha256:[0-9a-f]{64}"',
        )
        self.assertRegex(
            helper,
            r'OPENSSL_IMAGE="alpine/openssl:[0-9.]+@sha256:[0-9a-f]{64}"',
        )
        self.assertRegex(
            helper,
            r'PYTHON_SQL_GUARD_IMAGE="python:[0-9.]+-bookworm@sha256:[0-9a-f]{64}"',
        )

    def test_migration_sql_guard_rejects_transaction_escape(self) -> None:
        guard = SCRIPTS / "check-cloud-migration-sql.py"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            safe = root / "001_safe.sql"
            safe.write_text(
                "-- COMMIT in a comment\n"
                "create table safe_value(value text default 'ROLLBACK');\n"
                "do $$ begin perform 'BEGIN'; end $$;\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(guard), str(root)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            unsafe = root / "002_escape.sql"
            payloads = (
                "create table leaked(value integer); COMMIT; select 1/0;\n",
                "create table foo$tag$bar(id int); COMMIT; "
                "create table baz$tag$qux(id int);\n",
                "create table foo·$tag$bar(id int); COMMIT; "
                "create table baz$tag$qux(id int);\n",
                "select E'a\\'b'; create table escaped_guard_bypass(id int); "
                "COMMIT; select '--resync'; select 1/0;\n",
            )
            for payload in payloads:
                with self.subTest(payload=payload):
                    unsafe.write_text(payload, encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, str(guard), str(root)],
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("top-level COMMIT transaction control", result.stderr)

    def test_restore_is_drill_only_and_production_runbook_remains_authoritative(self) -> None:
        script = (SCRIPTS / "cloud-restore.sh").read_text(encoding="utf-8")
        guide = (STACK / "docs" / "CLOUD_DATABASE_RECOVERY.md").read_text(encoding="utf-8")
        self.assertIn("CLOUD_DB_TARGET_KIND", script)
        self.assertIn("isolated-drill", script)
        self.assertIn("target_app_objects", script)
        self.assertIn("isolated target app scope is no longer empty", script)
        self.assertIn("--single-transaction -f /restore-apply.sql", script)
        self.assertIn("production restore is intentionally unsupported", script)
        self.assertIn("does **not** ship a generic production-restore button", guide)
        self.assertIn("ROLLBACK.md", guide)

    def test_ci_runs_the_contract_and_parses_all_generated_scripts(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_cloud_database_recovery_contract", workflow)
        for name in ("cloud-db-lib.sh", "cloud-snapshot.sh", "cloud-migrate.sh", "cloud-restore.sh"):
            self.assertIn(name, workflow)


class CloudDatabaseRecoveryBehaviorContract(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.temp_root = Path(self.temp.name)
        self.output = self.temp_root / "generated"
        subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                "--defaults",
                "--set",
                "stack=supabase-flutter",
                "--set",
                "project_slug=recovery-test",
                "--output",
                str(self.output),
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONUTF8": "1"},
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        authorization_key = self.output / "config" / "cloud-db-owner-public.pem"
        authorization_key.parent.mkdir(parents=True, exist_ok=True)
        authorization_key.write_text(
            "-----BEGIN PUBLIC KEY-----\nSYNTHETIC-CONTRACT-KEY\n-----END PUBLIC KEY-----\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "init", "-q"],
            cwd=self.output,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "-c", "user.name=Contract", "-c", "user.email=contract@example.invalid", "add", "-A"],
            cwd=self.output,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Contract",
                "-c",
                "user.email=contract@example.invalid",
                "commit",
                "-qm",
                "test fixture",
            ],
            cwd=self.output,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.fake_bin = self.temp_root / "bin"
        self.fake_bin.mkdir()
        self.docker_log = self.temp_root / "docker.log"
        fake_docker = self.fake_bin / "docker"
        fake_docker.write_text(
            "#!/usr/bin/env sh\n"
            f"printf '%s\\n' \"$*\" >> '{shell_path(self.docker_log)}'\n"
            "case \"$*\" in\n"
            "  *\"pg_control_system()\"*) printf '%s\\n' '123456789:16384'; exit 0 ;;\n"
            "  *\"alpine/openssl\"*\"base64 -d -A\"*) printf '%s' 'SIGNATURE'; exit 0 ;;\n"
            "  *\"alpine/openssl\"*\"dgst -sha256 -verify\"*) exit 0 ;;\n"
            "esac\n"
            "exit 97\n",
            encoding="utf-8",
        )
        fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def script(self, name: str) -> Path:
        return self.output / "scripts" / name

    def test_default_invocations_are_true_noops(self) -> None:
        env = clean_cloud_env()
        env["PATH"] = os.pathsep.join((str(self.fake_bin), env.get("PATH", "")))
        calls = (
            ("cloud-snapshot.sh", ("create",)),
            ("cloud-migrate.sh", ()),
            (
                "cloud-restore.sh",
                ("fsdb-prod-1999999999-abcdef0-0123456789abcdef.dump",),
            ),
        )
        for name, args in calls:
            with self.subTest(script=name):
                result = run_script(self.script(name), *args, env=env, cwd=self.output)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.docker_log.exists())
        self.assertFalse((self.output / ".firestarter" / "cloud-db-recovery").exists())

    def test_snapshot_prepare_is_redacted_and_read_only(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        result = run_script(
            self.script("cloud-snapshot.sh"),
            "create",
            "--prepare",
            "--plan-nonce",
            "0123456789abcdef",
            "--approval-expires-at",
            str(int(time.time()) + 600),
            env=env,
            cwd=self.output,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"scope_sha256=[0-9a-f]{64}")
        self.assertRegex(result.stdout, r"target_database_sha256=[0-9a-f]{64}")
        combined = result.stdout + result.stderr
        for canary in (
            "DB_SECRET_CANARY",
            "BUCKET_CANARY",
            "endpoint-canary.invalid",
            "ACCESS_KEY_CANARY",
            "SECRET_KEY_CANARY",
        ):
            self.assertNotIn(canary, combined)
        docker_calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("pg_control_system()", docker_calls)
        self.assertNotIn("pg_dump", docker_calls)
        self.assertNotIn("copyto", docker_calls)
        self.assertFalse((self.output / ".firestarter" / "cloud-db-recovery").exists())

    def test_database_uri_cannot_override_reviewed_transport_options(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        env["CLOUD_DB_URL"] = "postgresql://synthetic:synthetic@example.invalid/app?sslmode=disable"
        result = run_script(
            self.script("cloud-snapshot.sh"),
            "create",
            "--prepare",
            "--plan-nonce",
            "0123456789abcdef",
            "--approval-expires-at",
            str(int(time.time()) + 600),
            env=env,
            cwd=self.output,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("URI options can override reviewed transport controls", result.stderr)
        self.assertFalse(self.docker_log.exists())

    def test_database_tls_cannot_be_downgraded(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        env["CLOUD_DB_SSLMODE"] = "require"
        result = run_script(
            self.script("cloud-snapshot.sh"),
            "create",
            "--prepare",
            "--plan-nonce",
            "0123456789abcdef",
            "--approval-expires-at",
            str(int(time.time()) + 600),
            env=env,
            cwd=self.output,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unauthenticated TLS is refused", result.stderr)
        self.assertFalse(self.docker_log.exists())

    def test_xtrace_cannot_print_secret_values(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        result = subprocess.run(
            [
                BASH,
                "-x",
                str(self.script("cloud-snapshot.sh")),
                "create",
                "--prepare",
                "--plan-nonce",
                "0123456789abcdef",
                "--approval-expires-at",
                str(int(time.time()) + 600),
            ],
            cwd=self.output,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        combined = result.stdout + result.stderr + self.docker_log.read_text(encoding="utf-8")
        for canary in (
            "DB_SECRET_CANARY",
            "ACCESS_KEY_CANARY",
            "SECRET_KEY_CANARY",
        ):
            self.assertNotIn(canary, combined)

    def test_execute_requires_matching_fresh_authorization_before_external_write(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        expires = str(int(time.time()) + 600)
        base_args = (
            "create",
            "--execute",
            "--plan-nonce",
            "0123456789abcdef",
            "--approval-expires-at",
            expires,
            "--authorization-id",
            "owner-decision-0001",
        )
        wrong = run_script(
            self.script("cloud-snapshot.sh"),
            *base_args,
            "--approved-scope",
            "0" * 64,
            env=env,
            cwd=self.output,
        )
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("approved scope does not match", wrong.stderr)
        docker_calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("pg_control_system()", docker_calls)
        self.assertNotIn("pg_dump", docker_calls)
        self.assertNotIn("copyto", docker_calls)

    def test_consumed_authorization_cannot_replay_and_journal_is_redacted(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        nonce = "fedcba9876543210"
        expires = str(int(time.time()) + 600)
        preview = run_script(
            self.script("cloud-snapshot.sh"),
            "create",
            "--prepare",
            "--plan-nonce",
            nonce,
            "--approval-expires-at",
            expires,
            env=env,
            cwd=self.output,
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        scope = re.search(r"scope_sha256=([0-9a-f]{64})", preview.stdout)
        self.assertIsNotNone(scope)
        args = (
            "create",
            "--execute",
            "--plan-nonce",
            nonce,
            "--approval-expires-at",
            expires,
            "--authorization-id",
            "owner-decision-replay-0001",
            "--approved-scope",
            scope.group(1),
        )
        first = run_script(self.script("cloud-snapshot.sh"), *args, env=env, cwd=self.output)
        self.assertNotEqual(first.returncode, 0)
        self.assertTrue(self.docker_log.exists(), first.stdout + first.stderr)
        calls_after_first = self.docker_log.read_text(encoding="utf-8")
        for canary in ("DB_SECRET_CANARY", "ACCESS_KEY_CANARY", "SECRET_KEY_CANARY"):
            self.assertNotIn(canary, calls_after_first + first.stdout + first.stderr)

        second = run_script(self.script("cloud-snapshot.sh"), *args, env=env, cwd=self.output)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("already consumed", second.stderr)
        replay_calls = self.docker_log.read_text(encoding="utf-8")[len(calls_after_first):]
        self.assertIn("pg_control_system()", replay_calls)
        self.assertNotIn("pg_dump", replay_calls)
        self.assertNotIn("copyto", replay_calls)

        journal = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.output / ".firestarter" / "cloud-db-recovery").rglob("*")
            if path.is_file()
        )
        for canary in (
            "DB_SECRET_CANARY",
            "BUCKET_CANARY",
            "endpoint-canary.invalid",
            "ACCESS_KEY_CANARY",
            "SECRET_KEY_CANARY",
        ):
            self.assertNotIn(canary, journal)
        self.assertIn("status=indeterminate", journal)

    def test_dirty_source_and_missing_signature_cannot_reach_external_write(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        nonce = "aabbccddeeff0011"
        expires = str(int(time.time()) + 600)
        preview = run_script(
            self.script("cloud-snapshot.sh"),
            "create",
            "--prepare",
            "--plan-nonce",
            nonce,
            "--approval-expires-at",
            expires,
            env=env,
            cwd=self.output,
        )
        scope = re.search(r"scope_sha256=([0-9a-f]{64})", preview.stdout)
        self.assertIsNotNone(scope)
        args = (
            "create",
            "--execute",
            "--plan-nonce",
            nonce,
            "--approval-expires-at",
            expires,
            "--authorization-id",
            "owner-decision-dirty-0001",
            "--approved-scope",
            scope.group(1),
        )

        without_signature = dict(env)
        without_signature.pop("CLOUD_DB_AUTHORIZATION_SIGNATURE")
        missing = run_script(
            self.script("cloud-snapshot.sh"), *args, env=without_signature, cwd=self.output
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("CLOUD_DB_AUTHORIZATION_SIGNATURE is required", missing.stderr)
        self.assertFalse((self.output / ".firestarter" / "cloud-db-recovery").exists())

        calls_before_dirty = self.docker_log.read_text(encoding="utf-8")
        readme = self.output / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\ndirty\n", encoding="utf-8")
        dirty = run_script(self.script("cloud-snapshot.sh"), *args, env=env, cwd=self.output)
        self.assertNotEqual(dirty.returncode, 0)
        self.assertIn("clean source checkout", dirty.stderr)
        self.assertEqual(self.docker_log.read_text(encoding="utf-8"), calls_before_dirty)

    def test_restore_rejects_latest_traversal_and_non_drill_target_before_docker(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        cases = ("latest", "../snapshot.dump", "bad:name.dump", "/tmp/snapshot.dump")
        for snapshot in cases:
            with self.subTest(snapshot=snapshot):
                result = run_script(
                    self.script("cloud-restore.sh"), snapshot, "--prepare", env=env, cwd=self.output
                )
                self.assertNotEqual(result.returncode, 0)
        exact = "fsdb-prod-1999999999-abcdef0-0123456789abcdef.dump"
        result = run_script(
            self.script("cloud-restore.sh"),
            exact,
            "--prepare",
            "--target-attestation",
            "attestation-0001",
            "--verification-plan",
            "verification-0001",
            env=env,
            cwd=self.output,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("production restore is intentionally unsupported", result.stderr)
        self.assertFalse(self.docker_log.exists())

    def test_expired_authorization_fails_before_docker(self) -> None:
        env = configured_env(self.temp_root, self.fake_bin)
        nonce = "0123456789abcdef"
        expires = str(int(time.time()) - 1)
        preview = run_script(
            self.script("cloud-snapshot.sh"),
            "create",
            "--prepare",
            "--plan-nonce",
            nonce,
            "--approval-expires-at",
            expires,
            env=env,
            cwd=self.output,
        )
        scope = re.search(r"scope_sha256=([0-9a-f]{64})", preview.stdout)
        self.assertIsNotNone(scope)
        result = run_script(
            self.script("cloud-snapshot.sh"),
            "create",
            "--execute",
            "--plan-nonce",
            nonce,
            "--approval-expires-at",
            expires,
            "--authorization-id",
            "owner-decision-expired-0001",
            "--approved-scope",
            scope.group(1),
            env=env,
            cwd=self.output,
        )
        self.assertNotEqual(result.returncode, 0)
        docker_calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("pg_control_system()", docker_calls)
        self.assertNotIn("pg_dump", docker_calls)
        self.assertNotIn("copyto", docker_calls)


class CloudDatabaseRecoveryGeneratorContract(unittest.TestCase):
    def test_project_slug_cannot_form_an_unsafe_sql_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "unsafe"
            result = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--defaults",
                    "--set",
                    "stack=supabase-flutter",
                    "--set",
                    "project_slug=unsafe';drop-table",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONUTF8": "1"},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_only_supabase_stack_stamps_recovery_surface_without_token_leaks(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp)
            for stack in config["stack"]:
                with self.subTest(stack=stack):
                    output = output_root / stack
                    subprocess.run(
                        [
                            sys.executable,
                            str(GENERATOR),
                            "--defaults",
                            "--set",
                            f"stack={stack}",
                            "--output",
                            str(output),
                        ],
                        cwd=ROOT,
                        env={**os.environ, "PYTHONUTF8": "1"},
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    recovery_script = output / "scripts" / "cloud-snapshot.sh"
                    if stack == "supabase-flutter":
                        self.assertTrue(recovery_script.is_file())
                        self.assertTrue(os.access(recovery_script, os.X_OK))
                        for name in (
                            "cloud-db-lib.sh",
                            "cloud-snapshot.sh",
                            "cloud-migrate.sh",
                            "cloud-restore.sh",
                        ):
                            text = (output / "scripts" / name).read_text(encoding="utf-8")
                            self.assertNotIn("{{", text)
                        self.assertTrue((output / "docs" / "CLOUD_DATABASE_RECOVERY.md").is_file())
                    else:
                        self.assertFalse(recovery_script.exists())


if __name__ == "__main__":
    unittest.main()
