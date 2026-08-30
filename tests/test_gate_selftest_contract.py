"""Contracts for Docker gate source-visibility self-tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("GATE_SELFTEST_BASH", "bash")
GUARD = ROOT / "template" / "scripts" / "gate-selftest.sh"
GUARD_TEST = ROOT / "template" / "scripts" / "tests" / "test-gate-selftest.sh"

EXPECTED_CASES = {
    "chrome-extension": ("--case node-tools . /work $(RUN)",),
    "fastapi-next": (
        "--case backend-tools backend /app $(TOOLS)",
        "--case frontend-tools frontend /app $(NODE)",
    ),
    "node-notifier": ("--case test-image . /app $(TEST_RUN)",),
    "supabase-flutter": (
        "--case dart services /pkg $(DART_RUN)",
        "--case flutter app /app $(FLUTTER_RUN)",
        "--case splash splash /splash $(SPLASH_RUN)",
    ),
}

EXPECTED_REAL_TARGET_RECIPES = {
    "chrome-extension": {
        "test-unit": "$(RUN) npm run test:unit",
        "typecheck": "$(RUN) npm run typecheck",
        "build": "$(RUN) npm run build",
    },
    "fastapi-next": {
        "backend-test": "$(TOOLS) pytest -q",
        "backend-lint": '$(TOOLS) sh -c "ruff format --check . && ruff check . && mypy app"',
        "frontend-typecheck": "$(NODE) npm run typecheck",
        "frontend-build": "$(NODE) npm run build",
    },
    "node-notifier": {
        "test-run": "$(TEST_RUN) npm run test:all",
        "lint": "$(TEST_RUN) npm run check",
    },
    "supabase-flutter": {
        "dart-test": '$(DART_RUN) sh -c "dart pub get && dart test"',
        "flutter-analyze": '$(FLUTTER_RUN) sh -c "flutter pub get && flutter analyze --fatal-infos"',
        "flutter-format-check": '$(FLUTTER_RUN) sh -c "dart format --output=none --set-exit-if-changed ."',
        "flutter-test": '$(FLUTTER_RUN) sh -c "flutter pub get && flutter test"',
        "splash-check": '$(SPLASH_RUN) sh -c "npm ci --no-audit --no-fund && npm run check"',
        "splash-build": '$(SPLASH_RUN) sh -c "npm ci --no-audit --no-fund && npm run build"',
    },
}

EXPECTED_RUNNER_DEFINITIONS = {
    "chrome-extension": {
        "COMPOSE": "docker compose",
        "RUN_FLAGS": "",
        "RUN": "$(COMPOSE) --profile tools run --rm $(RUN_FLAGS) node-tools",
    },
    "fastapi-next": {
        "DC": "docker compose",
        "RUN_FLAGS": "",
        "TOOLS": "$(DC) --profile tools run --rm $(RUN_FLAGS) backend-tools",
        "NODE": "$(DC) --profile node run --rm $(RUN_FLAGS) frontend-tools",
    },
    "node-notifier": {
        "DC": "docker compose",
        "RUN_FLAGS": "",
        "TEST_RUN": "$(DC) --profile test run --build --rm $(RUN_FLAGS) test",
    },
    "supabase-flutter": {
        "DC": "docker compose",
        "RUN_FLAGS": "",
        "DART_RUN": "$(DC) --profile dart run --rm $(RUN_FLAGS) dart",
        "FLUTTER_RUN": "$(DC) --profile flutter run --rm $(RUN_FLAGS) flutter",
        "SPLASH_RUN": "$(DC) --profile splash run --rm $(RUN_FLAGS) splash",
    },
}

EXPECTED_COMPOSE_MOUNTS = {
    "chrome-extension": {"node-tools": "      - ./:/work"},
    "fastapi-next": {
        "backend-tools": "      - ./backend:/app",
        "frontend-tools": "      - ./frontend:/app",
    },
    "supabase-flutter": {
        "dart": "      - ./services:/pkg",
        "flutter": "      - ./app:/app",
        "splash": "      - ./splash:/splash",
    },
}

HOSTED_GUARD_COMMAND = "MAKE=make MAKEFLAGS= MFLAGS= GNUMAKEFLAGS= make gate-selftest"
RELEASE_PARITY_RAW_VARIABLES = frozenset({
    "RELEASE_PARITY_PAIRS",
    "RELEASE_VENDOR_MANIFEST",
    "RELEASE_VENDOR_SOURCE",
    "RELEASE_VENDOR_RELEASE",
})
RELEASE_PARITY_VARIABLE_PATTERN = (
    r"RELEASE_(?:PARITY_PAIRS|VENDOR_MANIFEST|VENDOR_SOURCE|VENDOR_RELEASE)"
)
RELEASE_PARITY_EXPORT = (
    "export RELEASE_PARITY_PAIRS RELEASE_VENDOR_MANIFEST "
    "RELEASE_VENDOR_SOURCE RELEASE_VENDOR_RELEASE"
)


def compose_service_block(compose: str, service: str) -> str:
    matches = list(re.finditer(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        compose,
    ))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one Compose service: {service}")
    return matches[0].group(1)


def make_target(makefile: str, target: str) -> tuple[list[str], list[str]]:
    lines = makefile.splitlines()
    matches = [
        index
        for index, line in enumerate(lines)
        if not line.startswith("\t")
        and not line.lstrip().startswith("#")
        and ":" in line
        and target in line.split(":", 1)[0].split()
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one active Make target: {target}")
    index = matches[0]
    line = lines[index]
    prerequisites = line.split("##", 1)[0].split(":", 1)[1].split()
    recipe: list[str] = []
    for candidate in lines[index + 1 :]:
        if candidate.startswith("\t"):
            recipe.append(candidate[1:])
            continue
        if not candidate.strip() or candidate.lstrip().startswith("#"):
            continue
        break
    return prerequisites, recipe


def make_variable(makefile: str, name: str) -> str:
    values = re.findall(
        rf"(?m)^{re.escape(name)}[ \t]*:=[ \t]*(.*?)[ \t]*$",
        makefile,
    )
    if len(values) != 1:
        raise AssertionError(f"expected exactly one immediate Make variable: {name}")
    return values[0]


def is_release_parity_raw_self_freeze(line: str) -> bool:
    """Allow only the exact self-freeze that preserves RELEASE_* input bytes."""
    return line in {
        f"override {variable} := $(value {variable})"
        for variable in RELEASE_PARITY_RAW_VARIABLES
    }


def is_release_parity_control(line: str) -> bool:
    modifiers = r"(?:(?:override|export|private)[ \t]+)*"
    return bool(
        re.match(rf"^{modifiers}{RELEASE_PARITY_VARIABLE_PATTERN}\b", line)
        or re.match(
            rf"^{modifiers}(?:undefine|unexport)[ \t]+"
            rf"{RELEASE_PARITY_VARIABLE_PATTERN}\b",
            line,
        )
    )


def assert_release_parity_raw_self_freezes(stack: str, makefile: str) -> None:
    lines = makefile.splitlines()
    for variable in RELEASE_PARITY_RAW_VARIABLES:
        expected = f"override {variable} := $(value {variable})"
        if lines.count(expected) != 1:
            raise AssertionError(
                f"{stack} must contain exactly one canonical {variable} raw self-freeze"
            )
    if lines.count(RELEASE_PARITY_EXPORT) != 1:
        raise AssertionError(f"{stack} must contain exactly one canonical RELEASE_* export")


def assert_make_guard_wiring(stack: str, makefile: str) -> None:
    for line in makefile.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line.startswith("\t"):
            continue
        if line.endswith("\\"):
            raise AssertionError(f"{stack} contains a continued top-level Make line")
        if re.match(
            r"^(?:(?:override|export|private)[ \t]+)*(?:MAKE|MAKEFLAGS|MFLAGS|GNUMAKEFLAGS|SHELL|\.SHELLFLAGS|\.EXTRA_PREREQS|PATH|BASH_ENV|ENV)[ \t]*(?::=|\+=|\?=|!=|=)",
            stripped,
        ):
            raise AssertionError(f"{stack} contains a failure-altering Make control")
        if "!=" in stripped:
            raise AssertionError(f"{stack} contains a parse-time shell assignment")
        if re.match(
            r"^(?:-?include|sinclude|define|override[ \t]+define|ifeq|ifneq|ifdef|ifndef|else|endif|load)\b",
            stripped,
        ):
            raise AssertionError(f"{stack} contains dynamic Make source")
        if (
            is_release_parity_control(stripped)
            and not is_release_parity_raw_self_freeze(stripped)
            and stripped != RELEASE_PARITY_EXPORT
        ):
            raise AssertionError(f"{stack} contains non-canonical RELEASE_* control")
        if stripped.startswith("$"):
            raise AssertionError(f"{stack} contains a top-level Make expansion directive")
        if re.search(r"\$(?:\(|\{)[ \t]*eval\b", stripped):
            raise AssertionError(f"{stack} contains dynamic Make evaluation")
        if "$" in stripped and not is_release_parity_raw_self_freeze(stripped):
            assignment = re.match(r"^([A-Za-z0-9_.-]+)[ \t]*:=[ \t]*(.*)$", stripped)
            if (
                assignment is None
                or assignment.group(1) not in EXPECTED_RUNNER_DEFINITIONS[stack]
                or assignment.group(2) != EXPECTED_RUNNER_DEFINITIONS[stack][assignment.group(1)]
            ):
                raise AssertionError(f"{stack} contains an unbounded Make expansion")
        if ":" in line and not line.startswith(":=", line.index(":")):
            targets, rule_body = line.split(":", 1)
            if "$" in targets or ".IGNORE" in targets.split():
                raise AssertionError(f"{stack} contains a dynamic or failure-ignoring Make rule")
            if re.search(r"(?::=|\+=|\?=|!=|=)", rule_body.split("##", 1)[0]):
                raise AssertionError(f"{stack} contains a target-specific variable assignment")
    assert_release_parity_raw_self_freezes(stack, makefile)
    for variable, expected in EXPECTED_RUNNER_DEFINITIONS[stack].items():
        if make_variable(makefile, variable) != expected:
            raise AssertionError(f"{stack} has a drifted or unsafe {variable} runner definition")
    phony_targets: set[str] = set()
    for line in makefile.splitlines():
        if line.startswith(".PHONY:"):
            phony_targets.update(line.split("#", 1)[0].split(":", 1)[1].split())
    required_phony = {
        "gate-selftest",
        "gate-selftest-run",
        "release-parity",
        "test",
        "precommit",
        *EXPECTED_REAL_TARGET_RECIPES[stack],
    }
    if not required_phony.issubset(phony_targets):
        raise AssertionError(f"{stack} guard and required runner targets must remain phony")
    for target in ("test", "precommit"):
        prerequisites, _ = make_target(makefile, target)
        if not prerequisites or prerequisites[0] != "gate-selftest":
            raise AssertionError(f"{stack} {target} must gate source visibility first")
    entry_prerequisites, entry_recipe = make_target(makefile, "gate-selftest")
    expected_entry = '@$(MAKE) --no-print-directory gate-selftest-run RUN_FLAGS="--no-deps -T"'
    if entry_prerequisites or entry_recipe != [expected_entry]:
        raise AssertionError(f"{stack} gate-selftest must re-enter the exact runner definitions")
    runner_prerequisites, runner_recipe = make_target(makefile, "gate-selftest-run")
    runner = " ".join(line.rstrip("\\").strip() for line in runner_recipe)
    expected_runner = "@bash scripts/gate-selftest.sh " + " ".join(EXPECTED_CASES[stack])
    if runner_prerequisites or runner != expected_runner:
        raise AssertionError(f"{stack} gate-selftest-run must execute the universal guard")
    parity_prerequisites, parity_recipe = make_target(makefile, "release-parity")
    expected_parity_recipe = "@bash scripts/verify-release-parity.sh --from-env"
    if parity_prerequisites or parity_recipe != [expected_parity_recipe]:
        raise AssertionError(f"{stack} release-parity must execute only the exact guard")
    for target, expected_recipe in EXPECTED_REAL_TARGET_RECIPES[stack].items():
        _, recipe = make_target(makefile, target)
        if recipe != [expected_recipe]:
            raise AssertionError(f"{stack} {target} no longer invokes its exact guarded runner")


class UniqueSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def construct_unique_mapping(
    loader: UniqueSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise AssertionError(f"duplicate YAML mapping key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)


def assert_workflow_guard_first(workflow: str) -> None:
    document = yaml.load(workflow, Loader=UniqueSafeLoader)
    if not isinstance(document, dict):
        raise AssertionError("workflow must be a YAML mapping")
    if {"env", "defaults"} & document.keys():
        raise AssertionError("workflow-level controls must not redirect required gates")
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or "tests" not in jobs:
        raise AssertionError("workflow must define one Tests job")
    if any(isinstance(job, dict) and "defaults" in job for job in jobs.values()):
        raise AssertionError("job-level defaults must not redirect required gates")
    tests_job = jobs["tests"]
    if not isinstance(tests_job, dict):
        raise AssertionError("Tests job must be a mapping")
    if {"if", "continue-on-error", "needs", "env", "container"} & tests_job.keys():
        raise AssertionError("Tests job must be unconditional and blocking")
    steps = tests_job.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        raise AssertionError("Tests job must contain checkout and guard steps")
    if not all(isinstance(step, dict) for step in steps):
        raise AssertionError("every Tests step must be a mapping")
    checkout_ref = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    allowed_checkout_steps = (
        {"uses": checkout_ref},
        {"name": "Checkout", "uses": checkout_ref},
    )
    if steps[0] not in allowed_checkout_steps:
        raise AssertionError("Tests job must begin with the exact immutable checkout")
    expected_guard = {
        "name": "Prove Docker gates see current source",
        "shell": "bash",
        "working-directory": ".",
        "run": HOSTED_GUARD_COMMAND,
    }
    if steps[1] != expected_guard:
        raise AssertionError("gate-selftest must run immediately after checkout")
    if sum(step == expected_guard for step in steps) != 1:
        raise AssertionError("Tests job must contain exactly one guard step")
    project_gate_markers = (
        "make repo-hygiene",
        "make install",
        "make test",
        "make test-run",
        "docker compose",
    )
    for step in steps[:1]:
        command = step.get("run")
        if isinstance(command, str) and any(
            command.startswith(marker) for marker in project_gate_markers
        ):
            raise AssertionError("Tests job must run gate-selftest before project gates")


def yaml_mapping_lines(block: str, key: str) -> list[str]:
    lines = block.splitlines()
    header = f"    {key}:"
    matches = [index for index, line in enumerate(lines) if line == header]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one active Compose mapping: {key}")
    children: list[str] = []
    for candidate in lines[matches[0] + 1 :]:
        if not candidate.strip():
            children.append(candidate)
            continue
        indentation = len(candidate) - len(candidate.lstrip(" "))
        if indentation <= 4:
            break
        children.append(candidate)
    return children


def assert_source_visibility_mechanism(
    stack: str,
    makefile: str,
    compose: str,
    dockerfile: str = "",
    dockerignore: str = "",
) -> None:
    if stack == "node-notifier":
        runner_value = make_variable(makefile, "TEST_RUN").split("#", 1)[0]
        if "--build" not in runner_value.split():
            raise AssertionError("node-notifier test runner must rebuild current source")
        block = compose_service_block(compose, "test")
        build_lines = yaml_mapping_lines(block, "build")
        if "      context: ." not in build_lines:
            raise AssertionError("node-notifier test runner must build from the repository root")
        if "      target: test" not in build_lines:
            raise AssertionError("node-notifier test runner must select the test image stage")
        stage = re.search(
            r"(?ims)^FROM\s+\S+\s+AS\s+test\s*$\n(.*?)(?=^FROM\s|\Z)",
            dockerfile,
        )
        if stage is None:
            raise AssertionError("node-notifier Dockerfile must define the test image stage")
        if re.search(r"(?im)^[ \t]*(?:ADD|COPY|RUN)\b[^\n]*<<", stage.group(1)):
            raise AssertionError("node-notifier test stage must not hide source-copy evidence in a heredoc")
        if "COPY . ." not in stage.group(1).splitlines():
            raise AssertionError("node-notifier test image must copy current source")
        ignore_rules = [
            line.strip()
            for line in dockerignore.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not ignore_rules or ignore_rules[-1] != "!gate-selftest.*":
            raise AssertionError("node-notifier Docker context must explicitly re-include probe sentinels last")
        return
    for service, mount in EXPECTED_COMPOSE_MOUNTS[stack].items():
        volumes = yaml_mapping_lines(compose_service_block(compose, service), "volumes")
        if mount not in volumes:
            raise AssertionError(f"{service} must mount the source root used by its probe")


class GateSelftestBehaviorTests(unittest.TestCase):
    def test_dependency_light_behavior_matrix_and_mount_mutation(self) -> None:
        result = subprocess.run(
            [BASH, str(GUARD_TEST)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("removed-mount mutation exits non-zero", output)
        self.assertIn("dead runner is never reported as blind", output)
        self.assertIn("sentinels are cleaned in pass/fail modes", output)
        self.assertIn("gate-selftest guard self-test: ALL PASS", output)

    def test_guard_uses_argv_without_eval_and_unforgeable_per_run_markers(self) -> None:
        source = GUARD.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*eval\b")
        self.assertIn('"${runner[@]}" sh -c', source)
        self.assertIn("__FIRESTARTER_RUNNER_OK_${nonce}__", source)
        self.assertIn("__FIRESTARTER_SENTINEL_SEEN_${nonce}__", source)
        self.assertIn("Never echo runner-controlled bytes", source)
        self.assertIn("trap 'exit_cleanup \"$?\"' EXIT", source)
        self.assertIn("trap 'on_signal 129' HUP", source)
        self.assertIn("trap 'on_signal 130' INT", source)
        self.assertIn("trap 'on_signal 143' TERM", source)

    def test_guard_is_universal_and_contains_no_external_source_references(self) -> None:
        source = GUARD.read_text(encoding="utf-8") + GUARD_TEST.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"https?://|github\.com|git@[A-Za-z0-9.-]+:")
        self.assertNotRegex(source, r"[A-Za-z]:\\Users\\|/Users/|/home/[A-Za-z0-9._-]+/")

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX process-group signal proof")
    def test_signal_exits_remove_inflight_sentinels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = root / "slow-runner"
            runner.write_text(
                "#!/usr/bin/env bash\n"
                "trap 'exit 143' HUP INT TERM\n"
                "sleep 30\n",
                encoding="utf-8",
            )
            runner.chmod(0o755)
            for sent_signal, expected in (
                (signal.SIGHUP, 129),
                (signal.SIGINT, 130),
                (signal.SIGTERM, 143),
            ):
                with self.subTest(signal=sent_signal):
                    source = root / f"source-{sent_signal.value}"
                    logs = root / f"logs-{sent_signal.value}"
                    source.mkdir()
                    logs.mkdir()
                    env = os.environ.copy()
                    env["TMPDIR"] = str(logs)
                    process = subprocess.Popen(
                        [
                            BASH,
                            str(GUARD),
                            "--case",
                            "slow-runner",
                            str(source),
                            "/workspace",
                            str(runner),
                        ],
                        cwd=root,
                        env=env,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        start_new_session=True,
                    )
                    try:
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline and (
                            not list(source.glob("gate-selftest.*"))
                            or not list(logs.glob("gate-selftest-runner.*"))
                        ):
                            time.sleep(0.02)
                        self.assertTrue(list(source.glob("gate-selftest.*")), "sentinel was never planted")
                        private_logs = list(logs.glob("gate-selftest-runner.*"))
                        self.assertTrue(private_logs, "private runner log was never created")
                        self.assertEqual(stat.S_IMODE(private_logs[0].stat().st_mode), 0o600)
                        os.killpg(process.pid, sent_signal)
                        stdout, stderr = process.communicate(timeout=5)
                        self.assertEqual(process.returncode, expected, stdout + stderr)
                        self.assertNotIn("every Docker gate sees current source", stdout + stderr)
                        self.assertFalse(list(source.glob("gate-selftest.*")))
                        self.assertFalse(list(logs.glob("gate-selftest-runner.*")))
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=3)

    def test_temp_creation_is_parent_atomic_and_registered_before_signal_replay(self) -> None:
        source = GUARD.read_text(encoding="utf-8")
        self.assertNotIn("mktemp", source)
        self.assertIn("set -C", source)
        create = source.index('if : 2>/dev/null > "$candidate"; then')
        register = source.index('created+=("$tracked_temp")', create)
        replay = source.index('if [ "$pending_signal" -ne 0 ]; then', register)
        self.assertLess(create, register)
        self.assertLess(register, replay)

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX cleanup signal proof")
    def test_second_signal_cannot_interrupt_exit_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            logs = root / "logs"
            fake_bin = root / "bin"
            control = root / "control"
            for directory in (source, logs, fake_bin, control):
                directory.mkdir()
            runner = fake_bin / "mapped"
            runner.write_text(
                "#!/usr/bin/env bash\n"
                "host_dir=\"$1\"\ncontainer_dir=\"$2\"\nshift 2\n"
                "command=\"${3//${container_dir}/${host_dir}}\"\n"
                "sh -c \"$command\"\n",
                encoding="utf-8",
            )
            runner.chmod(0o755)
            fake_rm = fake_bin / "rm"
            fake_rm.write_text(
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                "  *gate-selftest.*)\n"
                "    if [ ! -f \"$CONTROL_DIR/first-rm\" ]; then\n"
                "      : > \"$CONTROL_DIR/first-rm\"\n"
                "      while [ ! -f \"$CONTROL_DIR/release-first\" ]; do sleep 0.02; done\n"
                "    elif [ ! -f \"$CONTROL_DIR/cleanup-rm\" ]; then\n"
                "      : > \"$CONTROL_DIR/cleanup-rm\"\n"
                "      while [ ! -f \"$CONTROL_DIR/release-cleanup\" ]; do sleep 0.02; done\n"
                "    fi\n"
                "    ;;\n"
                "esac\n"
                "exec /bin/rm \"$@\"\n",
                encoding="utf-8",
            )
            fake_rm.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            env["CONTROL_DIR"] = str(control)
            env["TMPDIR"] = str(logs)
            process = subprocess.Popen(
                [
                    BASH,
                    str(GUARD),
                    "--case",
                    "double-signal",
                    str(source),
                    "/workspace",
                    str(runner),
                    str(source),
                    "/workspace",
                ],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not (control / "first-rm").exists():
                    time.sleep(0.02)
                self.assertTrue((control / "first-rm").exists(), "initial cleanup never started")
                os.killpg(process.pid, signal.SIGHUP)
                (control / "release-first").touch()
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not (control / "cleanup-rm").exists():
                    time.sleep(0.02)
                self.assertTrue((control / "cleanup-rm").exists(), "EXIT cleanup never started")
                os.killpg(process.pid, signal.SIGTERM)
                (control / "release-cleanup").touch()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 129, stdout + stderr)
                self.assertNotIn("every Docker gate sees current source", stdout + stderr)
                self.assertFalse(list(source.glob("gate-selftest.*")))
                self.assertFalse(list(logs.glob("gate-selftest-runner.*")))
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)


class GateSelftestPlacementTests(unittest.TestCase):
    def test_release_parity_raw_self_freeze_exception_is_exact(self) -> None:
        valid = (
            "override RELEASE_PARITY_PAIRS := "
            "$(value RELEASE_PARITY_PAIRS)"
        )
        self.assertTrue(is_release_parity_raw_self_freeze(valid))
        for unsafe in (
            "RELEASE_PARITY_PAIRS := $(value RELEASE_PARITY_PAIRS)",
            "override RELEASE_PARITY_PAIRS := $(RELEASE_PARITY_PAIRS)",
            "override RELEASE_PARITY_PAIRS := $(value RELEASE_VENDOR_SOURCE)",
            "override OTHER := $(value OTHER)",
            f"{valid} $(shell true)",
            "override RELEASE_PARITY_PAIRS := $x",
            "override RELEASE_PARITY_PAIRS := $@",
            "override RELEASE_PARITY_PAIRS := $$",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertFalse(is_release_parity_raw_self_freeze(unsafe))

        makefile = (ROOT / "stacks" / "chrome-extension" / "Makefile").read_text(
            encoding="utf-8"
        )
        for unsafe in (
            "override RELEASE_PARITY_PAIRS := $(RELEASE_PARITY_PAIRS)",
            "override RELEASE_PARITY_PAIRS := $(value RELEASE_VENDOR_SOURCE)",
            f"{valid} $(shell true)",
            "override RELEASE_PARITY_PAIRS := $x",
            "override RELEASE_PARITY_PAIRS := $@",
            "override RELEASE_PARITY_PAIRS := $$",
        ):
            with self.subTest(wiring=unsafe), self.assertRaises(AssertionError):
                assert_make_guard_wiring(
                    "chrome-extension",
                    makefile.replace(valid, unsafe, 1),
                )
        for mutated in (
            makefile.replace(f"{valid}\n", "", 1),
            f"{makefile}\n{valid}\n",
            f"{makefile}\noverride RELEASE_PARITY_PAIRS := bypass.tsv\n",
            f"{makefile}\nRELEASE_PARITY_PAIRS += bypass.tsv\n",
            f"{makefile}\noverride undefine RELEASE_PARITY_PAIRS\n",
            f"{makefile}\nunexport RELEASE_PARITY_PAIRS\n",
            makefile.replace(
                RELEASE_PARITY_EXPORT,
                "export RELEASE_PARITY_PAIRS",
                1,
            ),
            makefile
            + "\n_BYPASS := \\\n\t$(eval gate-selftest: ; @:)\n",
            makefile.replace(
                "\t@bash scripts/verify-release-parity.sh --from-env",
                "\t@$(if $(RELEASE_PARITY_BYPASS),"
                "$(eval override RELEASE_PARITY_PAIRS := bypass.tsv),:)\n"
                "\t@bash scripts/verify-release-parity.sh --from-env",
                1,
            ),
            makefile
            + "\n.EXTRA_PREREQS := parity-prep\n"
            + "parity-prep:\n\t@:\n",
            makefile.replace(
                "\t@bash scripts/verify-release-parity.sh --from-env",
                "\t@bash scripts/verify-release-parity.sh --from-env\n\n"
                "\t@$(eval override RELEASE_PARITY_PAIRS := bypass.tsv)",
                1,
            ),
            makefile.replace(
                "\t@bash scripts/verify-release-parity.sh --from-env",
                "\t@bash scripts/verify-release-parity.sh --from-env\n"
                "# hidden recipe follows\n"
                "\t@$(eval override RELEASE_PARITY_PAIRS := bypass.tsv)",
                1,
            ),
        ):
            with self.subTest(canonical_count=True), self.assertRaises(AssertionError):
                assert_make_guard_wiring("chrome-extension", mutated)

    def test_declared_stacks_are_exactly_the_guarded_stacks(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config["stack"]), set(EXPECTED_CASES))

    def test_every_stack_reuses_real_runner_definitions_and_gates_first(self) -> None:
        for stack, cases in EXPECTED_CASES.items():
            with self.subTest(stack=stack):
                makefile = (ROOT / "stacks" / stack / "Makefile").read_text(encoding="utf-8")
                assert_make_guard_wiring(stack, makefile)
                active_guard = "\n".join(make_target(makefile, "gate-selftest-run")[1])
                for case in cases:
                    self.assertIn(case, active_guard)
                entry_noop = makefile.replace(
                    '\t@$(MAKE) --no-print-directory gate-selftest-run RUN_FLAGS="--no-deps -T"',
                    '\t@: # gate-selftest-run RUN_FLAGS="--no-deps -T"',
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, entry_noop)
                target_specific_make = makefile.replace(
                    "gate-selftest: ##",
                    "gate-selftest: override MAKE = true ##",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, target_specific_make)
                phony_removed = "\n".join(
                    re.sub(r"\bgate-selftest\b", "", line)
                    if line.startswith(".PHONY:")
                    else line
                    for line in makefile.splitlines()
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, phony_removed)
                commented_phony_lines: list[str] = []
                for line in makefile.splitlines():
                    if line.startswith(".PHONY:"):
                        tokens = line.split(":", 1)[1].split()
                        if "gate-selftest" in tokens:
                            tokens.remove("gate-selftest")
                            line = ".PHONY: " + " ".join(tokens) + " # gate-selftest"
                    commented_phony_lines.append(line)
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, "\n".join(commented_phony_lines))
                pattern_specific_make = makefile + "\ngate-%: MAKE = true\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, pattern_specific_make)
                duplicate = makefile + "\ngate-selftest:\n\t@:\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, duplicate)
                multi_target_override = makefile + "\ngate-selftest gate-selftest-run:\n\t@:\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, multi_target_override)
                duplicate_flags = makefile + "\nRUN_FLAGS := --entrypoint true\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, duplicate_flags)
                ignored_failures = makefile + "\n.IGNORE:\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, ignored_failures)
                hostile_makeflags = makefile + "\nMAKEFLAGS += -i\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, hostile_makeflags)
                hostile_shell = makefile + "\nSHELL := /bin/true\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, hostile_shell)
                hostile_recursive_make = makefile + "\nMAKE := true\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, hostile_recursive_make)
                hostile_shell_flags = makefile + "\n.SHELLFLAGS := -c true\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, hostile_shell_flags)
                parse_time_shell = (
                    makefile
                    + "\n_PRE_GUARD != printf 'exit 0\\n' > scripts/gate-selftest.sh\n"
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, parse_time_shell)
                expanded_override = (
                    makefile
                    + "\n_GUARDS := gate-selftest gate-selftest-run\n$(_GUARDS):\n\t@:\n"
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, expanded_override)
                brace_eval_override = (
                    makefile
                    + "\n_GUARD_OVERRIDE := gate-selftest: ; @:\n"
                    + "${eval $(_GUARD_OVERRIDE)}\n"
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, brace_eval_override)
                indirect_eval_override = (
                    makefile
                    + "\n_GUARD_OVERRIDE := gate-selftest: ; @:\n"
                    + "$(call eval,$(_GUARD_OVERRIDE))\n"
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, indirect_eval_override)
                assignment_eval_override = (
                    makefile
                    + "\n_GUARD_OVERRIDE := gate-selftest: ; @:\n"
                    + "_TRIGGER := $(call eval,$(_GUARD_OVERRIDE))\n"
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, assignment_eval_override)
                conditional_exclusion = "ifeq (1,0)\n" + makefile + "\nendif\n"
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, conditional_exclusion)
                _, real_recipe = next(iter(EXPECTED_REAL_TARGET_RECIPES[stack].items()))
                commented_real_gate = makefile.replace(
                    f"\t{real_recipe}",
                    f"\t@: # {real_recipe}",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, commented_real_gate)
                mutated = re.sub(
                    r"(?m)^\t@?bash scripts/gate-selftest\.sh(?:\s*\\)?$",
                    "\t@:",
                    makefile,
                    count=1,
                )
                with self.assertRaises(AssertionError):
                    assert_make_guard_wiring(stack, mutated)

    def test_every_runner_visibility_mechanism_is_semantically_pinned_and_mutation_proved(self) -> None:
        for stack in EXPECTED_CASES:
            with self.subTest(stack=stack):
                stack_root = ROOT / "stacks" / stack
                makefile = (stack_root / "Makefile").read_text(encoding="utf-8")
                compose = (stack_root / "docker-compose.yml").read_text(encoding="utf-8")
                dockerfile_path = stack_root / "Dockerfile"
                dockerfile = dockerfile_path.read_text(encoding="utf-8") if dockerfile_path.exists() else ""
                dockerignore_path = stack_root / ".dockerignore"
                dockerignore = dockerignore_path.read_text(encoding="utf-8") if dockerignore_path.exists() else ""
                assert_source_visibility_mechanism(stack, makefile, compose, dockerfile, dockerignore)
                if stack == "node-notifier":
                    with self.assertRaises(AssertionError):
                        assert_source_visibility_mechanism(
                            stack,
                            makefile.replace("run --build --rm", "run --rm # --build", 1),
                            compose,
                            dockerfile,
                            dockerignore,
                        )
                    with self.assertRaises(AssertionError):
                        assert_source_visibility_mechanism(
                            stack,
                            makefile,
                            compose,
                            dockerfile.replace(
                                "COPY . .",
                                "COPY <<EOF /tmp/note\nCOPY . .\nEOF",
                                1,
                            ),
                            dockerignore,
                        )
                    with self.assertRaises(AssertionError):
                        assert_source_visibility_mechanism(
                            stack,
                            makefile,
                            compose.replace(
                                "    build:\n      context: .",
                                "    labels:\n      context: .",
                                1,
                            ),
                            dockerfile,
                            dockerignore,
                        )
                    with self.assertRaises(AssertionError):
                        assert_source_visibility_mechanism(
                            stack,
                            makefile,
                            compose.replace(
                                "    build:\n",
                                "    build:\n      context: .\n      target: test\n    build:\n",
                                1,
                            ),
                            dockerfile,
                            dockerignore,
                        )
                    with self.assertRaises(AssertionError):
                        assert_source_visibility_mechanism(
                            stack,
                            makefile,
                            compose.replace("      target: test", "#      target: test", 1),
                            dockerfile,
                            dockerignore,
                        )
                    with self.assertRaises(AssertionError):
                        assert_source_visibility_mechanism(
                            stack,
                            makefile,
                            compose,
                            dockerfile.replace("COPY . .", "# COPY . .", 1),
                            dockerignore,
                        )
                    with self.assertRaises(AssertionError):
                        assert_source_visibility_mechanism(
                            stack,
                            makefile,
                            compose,
                            dockerfile.replace(" AS test", "", 1),
                            dockerignore,
                        )
                    with self.assertRaises(AssertionError):
                        assert_source_visibility_mechanism(
                            stack,
                            makefile,
                            compose,
                            dockerfile,
                            dockerignore.replace("!gate-selftest.*", "", 1),
                        )
                else:
                    for mount in EXPECTED_COMPOSE_MOUNTS[stack].values():
                        with self.assertRaises(AssertionError):
                            assert_source_visibility_mechanism(
                                stack,
                                makefile,
                                compose.replace(mount, f"#{mount}", 1),
                            )
                        with self.assertRaises(AssertionError):
                            assert_source_visibility_mechanism(
                                stack,
                                makefile,
                                compose.replace(
                                    f"    volumes:\n{mount}",
                                    f"    command: |\n{mount}",
                                    1,
                                ),
                            )
                        with self.assertRaises(AssertionError):
                            assert_source_visibility_mechanism(
                                stack,
                                makefile,
                                compose.replace(
                                    f"    volumes:\n{mount}",
                                    f"    volumes:\n{mount}\n    volumes:\n{mount}",
                                    1,
                                ),
                            )

    def test_existing_tests_job_runs_guard_before_other_project_gates(self) -> None:
        for stack in EXPECTED_CASES:
            with self.subTest(stack=stack):
                workflow = (
                    ROOT / "stacks" / stack / ".github" / "workflows" / "ci.yml"
                ).read_text(encoding="utf-8")
                assert_workflow_guard_first(workflow)
                commented = workflow.replace(
                    f"        run: {HOSTED_GUARD_COMMAND}",
                    f"        # run: {HOSTED_GUARD_COMMAND}",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(commented)
                ignored = workflow.replace(
                    f"        run: {HOSTED_GUARD_COMMAND}",
                    f"        continue-on-error: true\n        run: {HOSTED_GUARD_COMMAND}",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(ignored)
                hostile_env = workflow.replace(
                    f"        run: {HOSTED_GUARD_COMMAND}",
                    f"        env:\n          MAKEFLAGS: -i\n        run: {HOSTED_GUARD_COMMAND}",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(hostile_env)
                custom_shell = workflow.replace(
                    f"        run: {HOSTED_GUARD_COMMAND}",
                    f"        shell: /bin/true {{0}}\n        run: {HOSTED_GUARD_COMMAND}",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(custom_shell)
                redirected_guard = workflow.replace(
                    "        working-directory: .",
                    "        working-directory: .ci",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(redirected_guard)
                pre_guard_step = workflow.replace(
                    "      - name: Prove Docker gates see current source",
                    "      - name: Replace Makefile\n        run: cp .ci/Makefile Makefile\n\n"
                    "      - name: Prove Docker gates see current source",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(pre_guard_step)
                quoted_if = workflow.replace(
                    f"        run: {HOSTED_GUARD_COMMAND}",
                    f'        "if": ${{{{ false }}}}\n        run: {HOSTED_GUARD_COMMAND}',
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(quoted_if)
                nested_run = workflow.replace(
                    f"        run: {HOSTED_GUARD_COMMAND}",
                    f"        with:\n          run: {HOSTED_GUARD_COMMAND}",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(nested_run)
                conditional_job = workflow.replace(
                    "  tests:\n",
                    "  tests:\n    if: false\n",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(conditional_job)
                spaced_conditional_job = workflow.replace(
                    "  tests:\n",
                    "  tests:\n    if   : false\n",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(spaced_conditional_job)
                dependent_job = workflow.replace(
                    "  tests:\n",
                    "  tests:\n    needs: prerequisite\n",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(dependent_job)
                hostile_job_env = workflow.replace(
                    "  tests:\n",
                    "  tests:\n    env:\n      MAKE: /bin/true\n",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(hostile_job_env)
                quoted_workflow_env = workflow.replace(
                    "name: CI\n",
                    'name: CI\n"env":\n  BASH_ENV: .github/skip.sh\n',
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(quoted_workflow_env)
                redirected_defaults = workflow.replace(
                    "name: CI\n",
                    "name: CI\ndefaults:\n  run:\n    working-directory: .ci\n",
                    1,
                )
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(redirected_defaults)
                duplicate_job = workflow + "\n  tests:\n    runs-on: ubuntu-latest\n    steps: []\n"
                with self.assertRaises(AssertionError):
                    assert_workflow_guard_first(duplicate_job)

    def test_smoke_runs_classifier_tests_without_starting_docker(self) -> None:
        smoke = (ROOT / "template" / "scripts" / "smoke.sh").read_text(encoding="utf-8")
        self.assertIn("bash scripts/tests/test-gate-selftest.sh || fail=1", smoke)
        guard_test = GUARD_TEST.read_text(encoding="utf-8").lower()
        self.assertNotIn("docker compose", guard_test)
        self.assertNotIn("docker run", guard_test)

    def test_every_generated_stack_contains_the_guard_and_behavior_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            for answers in sorted((ROOT / "examples").glob("*.answers.json")):
                stack = answers.name.removesuffix(".answers.json")
                output = output_root / stack
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "bin" / "generate.py"),
                        "--values",
                        str(answers),
                        "--output",
                        str(output),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                generated_makefile = (output / "Makefile").read_text(encoding="utf-8")
                generated_workflow = (
                    output / ".github" / "workflows" / "ci.yml"
                ).read_text(encoding="utf-8")
                generated_compose = (output / "docker-compose.yml").read_text(
                    encoding="utf-8"
                )
                generated_dockerfile_path = output / "Dockerfile"
                generated_dockerfile = (
                    generated_dockerfile_path.read_text(encoding="utf-8")
                    if generated_dockerfile_path.exists()
                    else ""
                )
                generated_dockerignore_path = output / ".dockerignore"
                generated_dockerignore = (
                    generated_dockerignore_path.read_text(encoding="utf-8")
                    if generated_dockerignore_path.exists()
                    else ""
                )
                assert_make_guard_wiring(stack, generated_makefile)
                assert_workflow_guard_first(generated_workflow)
                assert_source_visibility_mechanism(
                    stack,
                    generated_makefile,
                    generated_compose,
                    generated_dockerfile,
                    generated_dockerignore,
                )
                self.assertTrue((output / "scripts" / "gate-selftest.sh").is_file())
                generated_test = output / "scripts" / "tests" / "test-gate-selftest.sh"
                self.assertTrue(generated_test.is_file())
                behavior = subprocess.run(
                    [BASH, str(generated_test)],
                    cwd=output,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    behavior.returncode,
                    0,
                    f"{stack}: {behavior.stdout}{behavior.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
