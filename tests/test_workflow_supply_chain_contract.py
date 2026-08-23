"""Contracts for immutable GitHub Action refs and their upkeep path."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("WORKFLOW_CONTRACT_BASH", "bash")
USES_LINE = re.compile(r'''^\s*(?:-\s*)?(?:uses|"uses"|'uses')\s*:\s*(.*?)\s*$''')
SEQUENCE_FLOW_CONTAINER = re.compile(r"^\s*-\s*[\{\[]")
FLOW_STEPS = re.compile(
    r'''(?:^|[\s,{])(?P<key>steps|"steps"|'steps')\s*:\s*\['''
)
FLOW_USES = re.compile(r'''(?:^|[\s,{])(?P<key>uses|"uses"|'uses')\s*:''')
BLOCK_STEPS_KEY = re.compile(r'''^\s*(?:steps|"steps"|'steps')\s*:\s*$''')
DIRECT_FLOW_STEPS = re.compile(r'''^\s*(?:steps|"steps"|'steps')\s*:\s*\[''')
EXPLICIT_KEY = re.compile(r"^\s*(?:-\s*)?\?")
ESCAPED_DOUBLE_KEY = re.compile(r'^\s*(?:-\s*)?"[^"]*\\[^"]*"\s*:')
FLOW_ESCAPED_DOUBLE_KEY = re.compile(r'"[^"]*\\[^"]*"\s*:')
BLOCK_SCALAR = re.compile(r':\s*[|>][0-9+-]*\s*(?:#.*)?$')
BLOCK_SCALAR_INDENT = re.compile(r"[|>](?:[+-]([1-9])|([1-9])[+-]?)\s*$")
BLOCK_SCALAR_USES = re.compile(
    r'''^\s*(?:-\s*)?(?:uses|"uses"|'uses')\s*:\s*[|>]'''
)
PLAIN_MAPPING_VALUE = re.compile(
    r'''^\s*(?:-\s*)?(?:[A-Za-z0-9_.-]+|"[^"]+"|'[^']+')\s*:\s+([^\s].*)$'''
)
PLAIN_SEQUENCE_VALUE = re.compile(r"^\s*-\s+([^\s].*)$")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
VERSION_NOTE = re.compile(r"v[0-9]+(?:\.[0-9]+){0,2}")


def split_yaml_comment(
    line: str,
    in_single: bool,
    in_double: bool,
    escaped: bool,
    flow_context: bool,
) -> tuple[str, str]:
    index = 0
    while index < len(line):
        char = line[index]
        if in_double:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_double = False
        elif in_single:
            if char == "'":
                if index + 1 < len(line) and line[index + 1] == "'":
                    index += 1
                else:
                    in_single = False
        elif char == '"' and quote_can_open(line, index, flow_context):
            in_double = True
        elif char == "'" and quote_can_open(line, index, flow_context):
            in_single = True
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index], line[index + 1 :].strip()
        index += 1
    return line, ""


def quote_can_open(line: str, position: int, flow_context: bool = False) -> bool:
    previous = position - 1
    while previous >= 0 and line[previous].isspace():
        previous -= 1
    if previous < 0:
        return True
    if line[previous] == "?":
        if position == 0 or not line[position - 1].isspace():
            return False
        previous -= 1
        while previous >= 0 and line[previous].isspace():
            previous -= 1
        return previous < 0 or line[previous] in ":-[{,?"
    if line[previous] == "-":
        if position == 0 or not line[position - 1].isspace():
            return False
        previous -= 1
        while previous >= 0 and line[previous].isspace():
            previous -= 1
        return previous < 0 or line[previous] in ":-[{,?"
    if line[previous] == ":" and position > 0 and not line[position - 1].isspace():
        previous -= 1
        if previous < 0 or line[previous] not in "\"']}":
            return False
        if not flow_context:
            prefix = line[:previous]
            if not re.search(r"(?:^|[:\-\[,])\s*[\{\[]", prefix):
                return False
        return True
    if line[previous] == ",":
        if flow_context:
            return True
        prefix = line[:previous]
        return bool(re.search(r"(?:^|[:\-\[,])\s*[\{\[]", prefix))
    if line[previous] in "[{":
        if flow_context:
            return True
        previous -= 1
        while previous >= 0 and line[previous].isspace():
            previous -= 1
        while previous >= 0 and line[previous] in "[{":
            previous -= 1
            while previous >= 0 and line[previous].isspace():
                previous -= 1
        return previous < 0 or line[previous] in ":-[{,?"
    return line[previous] in ":-[{,?"


def advance_yaml_quote_state(
    line: str,
    in_single: bool,
    in_double: bool,
    escaped: bool,
    flow_context: bool,
) -> tuple[bool, bool, bool]:
    index = 0
    while index < len(line):
        char = line[index]
        if in_double:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_double = False
        elif in_single:
            if char == "'":
                if index + 1 < len(line) and line[index + 1] == "'":
                    index += 1
                else:
                    in_single = False
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            break
        elif char == '"' and quote_can_open(line, index, flow_context):
            in_double = True
        elif char == "'" and quote_can_open(line, index, flow_context):
            in_single = True
        index += 1
    return in_single, in_double, escaped


def starts_outside_quotes(
    line: str,
    target: int,
    in_single: bool = False,
    in_double: bool = False,
    escaped: bool = False,
    flow_context: bool = False,
) -> bool:
    index = 0
    while index < target:
        char = line[index]
        if in_double:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_double = False
        elif in_single:
            if char == "'":
                if index + 1 < target and line[index + 1] == "'":
                    index += 1
                else:
                    in_single = False
        elif char == '"' and quote_can_open(line, index, flow_context):
            in_double = True
        elif char == "'" and quote_can_open(line, index, flow_context):
            in_single = True
        index += 1
    return not in_single and not in_double


def has_flow_steps(
    line: str, in_single: bool, in_double: bool, escaped: bool, flow_context: bool
) -> bool:
    return any(
        starts_outside_quotes(
            line, match.start("key"), in_single, in_double, escaped, flow_context
        )
        for match in FLOW_STEPS.finditer(line)
    )


def has_flow_uses(
    line: str, in_single: bool, in_double: bool, escaped: bool, flow_context: bool
) -> bool:
    for match in FLOW_USES.finditer(line):
        key_start = match.start("key")
        if not starts_outside_quotes(
            line, key_start, in_single, in_double, escaped, flow_context
        ):
            continue
        previous = key_start - 1
        while previous >= 0 and line[previous].isspace():
            previous -= 1
        if previous >= 0 and line[previous] in "{,":
            return True
    return False


def has_flow_explicit_key(
    line: str, in_single: bool, in_double: bool, escaped: bool, flow_context: bool
) -> bool:
    for index, char in enumerate(line):
        if char != "?" or not starts_outside_quotes(
            line, index, in_single, in_double, escaped, flow_context
        ):
            continue
        previous = index - 1
        while previous >= 0 and line[previous].isspace():
            previous -= 1
        if previous >= 0 and line[previous] in "{,":
            return True
    return False


def has_flow_escaped_double_key(
    line: str, in_single: bool, in_double: bool, escaped: bool, flow_context: bool
) -> bool:
    return any(
        starts_outside_quotes(
            line, match.start(), in_single, in_double, escaped, flow_context
        )
        for match in FLOW_ESCAPED_DOUBLE_KEY.finditer(line)
    )


def has_yaml_anchor_or_alias(
    line: str, in_single: bool, in_double: bool, escaped: bool, flow_context: bool
) -> bool:
    for index, char in enumerate(line):
        if char not in "&*" or index + 1 >= len(line):
            continue
        if line[index + 1].isspace() or line[index + 1] in "[]{},":
            continue
        if not starts_outside_quotes(
            line, index, in_single, in_double, escaped, flow_context
        ):
            continue
        previous = index - 1
        while previous >= 0 and line[previous].isspace():
            previous -= 1
        if previous < 0 or line[previous] in ":-[{,?":
            return True
    return False


def has_yaml_node_tag(
    line: str, in_single: bool, in_double: bool, escaped: bool, flow_context: bool
) -> bool:
    for index, char in enumerate(line):
        if char != "!":
            continue
        if starts_outside_quotes(
            line, index, in_single, in_double, escaped, flow_context
        ) and quote_can_open(line, index, flow_context):
            return True
    return False


def flow_mapping_opener(
    line: str, in_single: bool, in_double: bool, escaped: bool, flow_context: bool
) -> bool:
    for index, char in enumerate(line):
        if char != "{" or not starts_outside_quotes(
            line, index, in_single, in_double, escaped, flow_context
        ):
            continue
        if index > 0 and line[index - 1] == "$":
            continue
        if index > 1 and line[index - 2 : index] == "${":
            continue
        previous = index - 1
        while previous >= 0 and line[previous].isspace():
            previous -= 1
        if previous < 0 or line[previous] in ":-[,":
            return True
    return False


def flow_brace_delta(
    line: str, in_single: bool, in_double: bool, escaped: bool, flow_context: bool
) -> int:
    delta = 0
    for index, char in enumerate(line):
        if char in "{}" and starts_outside_quotes(
            line, index, in_single, in_double, escaped, flow_context
        ):
            delta += 1 if char == "{" else -1
    return delta


def workflow_paths(root: Path) -> list[Path]:
    directories = {root / ".github" / "workflows"}
    for scope in (root / "template", root / "stacks", root / "addons"):
        if not scope.is_dir():
            continue
        directories.update(
            path
            for path in scope.rglob("workflows")
            if path.is_dir() and path.parent.name == ".github"
        )
    return sorted(
        path
        for directory in directories
        if directory.is_dir()
        for path in directory.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    )


def uses_records(path: Path):
    scalar_key_indent: int | None = None
    scalar_body_indent: int | None = None
    pending_steps_indent: int | None = None
    pending_sequence_indent: int | None = None
    plain_scalar_indent: int | None = None
    yaml_in_single = False
    yaml_in_double = False
    yaml_escaped = False
    flow_mapping_depth = 0
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        indent = len(line) - len(line.lstrip(" \t"))
        if scalar_key_indent is not None:
            if not line.strip():
                continue
            if scalar_body_indent is None and indent > scalar_key_indent:
                scalar_body_indent = indent
                continue
            if scalar_body_indent is not None and indent >= scalar_body_indent:
                continue
            scalar_key_indent = None
            scalar_body_indent = None
        if plain_scalar_indent is not None:
            if not line.strip() or indent > plain_scalar_indent:
                continue
            plain_scalar_indent = None
        quote_start_single = yaml_in_single
        quote_start_double = yaml_in_double
        quote_start_escaped = yaml_escaped
        flow_mapping_context = flow_mapping_depth > 0
        visible, inline_note = split_yaml_comment(
            line,
            quote_start_single,
            quote_start_double,
            quote_start_escaped,
            flow_mapping_context,
        )
        yaml_in_single, yaml_in_double, yaml_escaped = advance_yaml_quote_state(
            line,
            quote_start_single,
            quote_start_double,
            quote_start_escaped,
            flow_mapping_context,
        )
        if not visible.strip():
            continue
        flow_mapping_starter = flow_mapping_opener(
            visible,
            quote_start_single,
            quote_start_double,
            quote_start_escaped,
            flow_mapping_context,
        )
        if flow_mapping_context or flow_mapping_starter:
            flow_mapping_depth = max(
                0,
                flow_mapping_depth
                + flow_brace_delta(
                    visible,
                    quote_start_single,
                    quote_start_double,
                    quote_start_escaped,
                    flow_mapping_context,
                ),
            )
        if pending_steps_indent is not None:
            if (
                not quote_start_single
                and not quote_start_double
                and visible.lstrip().startswith("[")
            ):
                raise ValueError(
                    f"{path}:{line_no}: flow-style steps lists are not allowed"
                )
            pending_steps_indent = None
        if pending_sequence_indent is not None:
            if (
                not quote_start_single
                and not quote_start_double
                and indent > pending_sequence_indent
                and visible.lstrip().startswith(("{", "["))
            ):
                raise ValueError(
                    f"{path}:{line_no}: flow-style sequence items are not allowed"
                )
            pending_sequence_indent = None
        if (
            not quote_start_single
            and not quote_start_double
            and BLOCK_SCALAR_USES.match(visible)
        ):
            raise ValueError(f"{path}:{line_no}: uses values must stay on one line")
        if not quote_start_single and not quote_start_double and BLOCK_SCALAR.search(visible):
            sequence_prefix = re.match(r"^\s*-\s+", visible)
            scalar_key_indent = sequence_prefix.end() if sequence_prefix else indent
            indicator = BLOCK_SCALAR_INDENT.search(visible)
            scalar_body_indent = (
                scalar_key_indent + int(indicator.group(1) or indicator.group(2))
                if indicator
                else None
            )
            continue
        if has_yaml_anchor_or_alias(
            visible,
            quote_start_single,
            quote_start_double,
            quote_start_escaped,
            flow_mapping_context or flow_mapping_starter,
        ):
            raise ValueError(f"{path}:{line_no}: YAML anchors and aliases are not allowed")
        if has_yaml_node_tag(
            visible,
            quote_start_single,
            quote_start_double,
            quote_start_escaped,
            flow_mapping_context or flow_mapping_starter,
        ):
            raise ValueError(f"{path}:{line_no}: YAML node tags are not allowed")
        if (
            (not quote_start_single and not quote_start_double and SEQUENCE_FLOW_CONTAINER.match(visible))
            or (not quote_start_single and not quote_start_double and DIRECT_FLOW_STEPS.match(visible))
            or (
                (flow_mapping_context or flow_mapping_starter)
                and (
                    has_flow_steps(
                        visible,
                        quote_start_single,
                        quote_start_double,
                        quote_start_escaped,
                        flow_mapping_context or flow_mapping_starter,
                    )
                    or has_flow_uses(
                        visible,
                        quote_start_single,
                        quote_start_double,
                        quote_start_escaped,
                        flow_mapping_context or flow_mapping_starter,
                    )
                )
            )
        ):
            raise ValueError(
                f"{path}:{line_no}: flow-style YAML containers are not allowed"
            )
        if not quote_start_single and not quote_start_double and BLOCK_STEPS_KEY.match(visible):
            pending_steps_indent = indent
            continue
        if not quote_start_single and not quote_start_double and re.match(r"^\s*-\s*$", visible):
            pending_sequence_indent = indent
            continue
        if not quote_start_single and not quote_start_double and ESCAPED_DOUBLE_KEY.match(visible):
            raise ValueError(
                f"{path}:{line_no}: escaped double-quoted YAML mapping keys are not allowed"
            )
        if (flow_mapping_context or flow_mapping_starter) and has_flow_escaped_double_key(
            visible,
            quote_start_single,
            quote_start_double,
            quote_start_escaped,
            flow_mapping_context or flow_mapping_starter,
        ):
            raise ValueError(
                f"{path}:{line_no}: escaped double-quoted YAML mapping keys are not allowed"
            )
        if not quote_start_single and not quote_start_double and EXPLICIT_KEY.match(visible):
            raise ValueError(
                f"{path}:{line_no}: explicit YAML mapping keys are not allowed"
            )
        if (flow_mapping_context or flow_mapping_starter) and has_flow_explicit_key(
            visible,
            quote_start_single,
            quote_start_double,
            quote_start_escaped,
            flow_mapping_context or flow_mapping_starter,
        ):
            raise ValueError(
                f"{path}:{line_no}: explicit YAML mapping keys are not allowed"
            )
        plain_match = (
            None
            if (
                flow_mapping_context
                or flow_mapping_starter
                or quote_start_single
                or quote_start_double
            )
            else PLAIN_MAPPING_VALUE.match(visible)
        )
        if plain_match and plain_match.group(1)[0] not in "\"'[{|>":
            sequence_prefix = re.match(r"^\s*-\s+", visible)
            plain_scalar_indent = sequence_prefix.end() if sequence_prefix else indent
        elif not (flow_mapping_context or flow_mapping_starter):
            sequence_match = PLAIN_SEQUENCE_VALUE.match(visible)
            if sequence_match and sequence_match.group(1)[0] not in "\"'[{|>":
                plain_scalar_indent = indent
        if flow_mapping_context and USES_LINE.match(visible):
            raise ValueError(f"{path}:{line_no}: flow-style uses keys are not allowed")
        match = (
            None
            if quote_start_single or quote_start_double
            else USES_LINE.match(visible)
        )
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        yield line_no, value, inline_note


class WorkflowSupplyChainContract(unittest.TestCase):
    def assert_remote_actions_are_pinned(self, root: Path) -> set[str]:
        seen: set[str] = set()
        paths = workflow_paths(root)
        self.assertTrue(paths, f"no workflow files found under {root}")
        for path in paths:
            for line_no, value, note in uses_records(path):
                if value.startswith("./") or value.startswith("docker://"):
                    continue
                with self.subTest(path=path.relative_to(root), line=line_no):
                    self.assertIn("@", value, "remote action is missing a ref")
                    action, ref = value.rsplit("@", 1)
                    self.assertRegex(ref, rf"^{FULL_SHA.pattern}$")
                    self.assertRegex(note, rf"^{VERSION_NOTE.pattern}$")
                    parts = action.split("/")
                    self.assertGreaterEqual(len(parts), 2)
                    seen.add("/".join(parts[:2]))
        return seen

    @staticmethod
    def assert_dependabot_updates_actions(test: unittest.TestCase, root: Path) -> None:
        config = root / ".github" / "dependabot.yml"
        test.assertTrue(config.is_file(), f"missing {config}")
        text = config.read_text(encoding="utf-8")
        test.assertRegex(text, r"package-ecosystem:\s*github-actions")
        test.assertRegex(text, r"(?m)^\s*directory:\s*/\s*$")

    def test_every_source_workflow_uses_an_immutable_action_commit(self) -> None:
        seen = self.assert_remote_actions_are_pinned(ROOT)
        self.assertTrue(
            {
                "actions/checkout",
                "actions/github-script",
                "actions/setup-node",
                "actions/upload-artifact",
                "supabase/setup-cli",
            }.issubset(seen)
        )
        self.assert_dependabot_updates_actions(self, ROOT)
        self.assert_dependabot_updates_actions(self, ROOT / "template")

        catalog_path = ROOT / ".github" / "workflows" / "action-pin-catalog.yml"
        catalog: dict[str, tuple[str, str]] = {}
        for _, value, note in uses_records(catalog_path):
            action, ref = value.rsplit("@", 1)
            catalog["/".join(action.split("/")[:2])] = (ref, note)
        self.assertEqual(catalog.keys(), seen)

        for path in workflow_paths(ROOT):
            for line_no, value, note in uses_records(path):
                if value.startswith("./") or value.startswith("docker://"):
                    continue
                action, ref = value.rsplit("@", 1)
                slug = "/".join(action.split("/")[:2])
                with self.subTest(parity=path.relative_to(ROOT), line=line_no):
                    self.assertEqual(
                        (ref, note),
                        catalog[slug],
                        "source pin drifted from the Dependabot-visible catalog",
                    )

    def test_all_enabled_stamps_keep_pins_updatable_and_smoke_green(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text())
        flags = sorted(
            key
            for key, value in config.items()
            if key.startswith("include_") and value == ["no", "yes"]
        )
        with tempfile.TemporaryDirectory() as temp:
            for answers in sorted((ROOT / "examples").glob("*.answers.json")):
                with self.subTest(answers=answers.name):
                    output = Path(temp) / answers.stem
                    command = [
                        "python3",
                        str(ROOT / "bin" / "generate.py"),
                        "--values",
                        str(answers),
                    ]
                    for flag in flags:
                        command.extend(("--set", f"{flag}=yes"))
                    command.extend(("--output", str(output)))
                    subprocess.run(command, cwd=ROOT, check=True, capture_output=True)

                    self.assert_remote_actions_are_pinned(output)
                    self.assert_dependabot_updates_actions(self, output)
                    result = subprocess.run(
                        [BASH, "scripts/smoke.sh"],
                        cwd=output,
                        check=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout)

    def test_smoke_rejects_quoted_and_flow_floating_refs_without_echoing_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "project"
            subprocess.run(
                [
                    "python3",
                    str(ROOT / "bin" / "generate.py"),
                    "--values",
                    str(ROOT / "examples" / "chrome-extension.answers.json"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            workflow = output / ".github" / "workflows" / "ci.yml"
            original = workflow.read_text(encoding="utf-8")
            replacements = {
                "quoted-key": '- "uses": actions/checkout@v4',
                "escaped-key": '- "\\u0075ses": actions/checkout@v4',
                "escaped-flow": '- { "\\u0075ses": actions/checkout@v4 }',
                "flow-mapping": "- { uses: actions/checkout@v4 }",
            }
            for shape, replacement in replacements.items():
                with self.subTest(shape=shape):
                    workflow.write_text(
                        re.sub(
                            r"- uses: actions/checkout@[0-9a-f]{40} # v4",
                            lambda _match: replacement,
                            original,
                            count=1,
                        ),
                        encoding="utf-8",
                    )
                    if shape in {"escaped-key", "escaped-flow", "flow-mapping"}:
                        expected = (
                            "escaped double-quoted"
                            if shape == "escaped-key"
                            else "flow-style YAML containers"
                        )
                        with self.assertRaisesRegex(ValueError, expected):
                            list(uses_records(workflow))
                    result = subprocess.run(
                        [BASH, "scripts/smoke.sh"],
                        cwd=output,
                        check=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn("action ref pin", result.stdout)
                    self.assertNotIn("actions/checkout@v4", result.stdout)

    def test_non_block_action_steps_are_rejected_without_echoing_the_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "project"
            subprocess.run(
                [
                    "python3",
                    str(ROOT / "bin" / "generate.py"),
                    "--values",
                    str(ROOT / "examples" / "chrome-extension.answers.json"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            workflow = output / ".github" / "workflows" / "non-block.yml"
            shapes = {
                "flow-sequence": """name: Synthetic flow sequence
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps: [{ uses: actions/checkout@v4 }]
""",
                "explicit-key": """name: Synthetic explicit key
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - ? uses # action key
        : actions/checkout@v4
""",
                "escaped-explicit-key": """name: Synthetic escaped explicit key
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - ? "\\u0075ses"
        : actions/checkout@v4
""",
                "flow-explicit-key": """name: Synthetic flow explicit key
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - { ? uses : actions/checkout@v4 }
""",
                "multiline-flow-key": """name: Synthetic multiline flow key
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - { "name": "Checkout"
        , "uses": "actions/checkout@v4" }
""",
                "multiline-flow-quote": """name: Synthetic multiline flow quote
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - { name: "mask
          }"
        , uses: actions/checkout@v4 }
""",
                "nested-job-flow": """name: Synthetic nested job flow
on: workflow_dispatch
jobs:
  test: { runs-on: ubuntu-latest, steps: [{ uses: actions/checkout@v4 }] }
""",
                "job-flow-uses": """name: Synthetic reusable job flow
on: workflow_dispatch
jobs:
  gate: { name: Why?'s rock-'n-roll Why:'s unpinned, uses: octo-org/example/.github/workflows/gate.yml@main }
""",
                "explicit-job-flow-uses": """name: Synthetic explicit reusable job flow
on: workflow_dispatch
jobs:
  gate: { ? uses : octo-org/example/.github/workflows/gate.yml@main }
""",
                "escaped-job-flow-uses": """name: Synthetic escaped reusable job flow
on: workflow_dispatch
jobs:
  gate: { "\\u0075ses": octo-org/example/.github/workflows/gate.yml@main }
""",
                "multiline-job-flow-uses": """name: Synthetic multiline reusable job flow
on: workflow_dispatch
jobs:
  gate: {
    uses: octo-org/example/.github/workflows/gate.yml@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # v1
  }
""",
                "indented-flow-uses": """name: Synthetic indented flow uses
on: workflow_dispatch
jobs:
  gate: {
    name: Repro,
      uses: octo-org/example/.github/workflows/gate.yml@main
  }
""",
                "same-indent-flow-steps": """name: Synthetic same-indent flow steps
on: workflow_dispatch
jobs:
  test: {
    runs-on: ubuntu-latest,
    steps:
    [{ uses: actions/checkout@v4 }]
  }
""",
                "split-sequence-flow": """name: Synthetic split sequence flow
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      -
        { uses: actions/checkout@v4 }
""",
                "block-scalar-uses": """name: Synthetic folded uses
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: >-
          actions/checkout@v4
""",
                "tagged-steps": """name: Synthetic tagged steps
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps: !!seq
      - uses: actions/checkout@v4
""",
                "nonspecific-tagged-steps": """name: Synthetic nonspecific tagged steps
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps: !
      - uses: actions/checkout@v4
""",
                "anchored-flow-sequence": """name: Synthetic anchored flow
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps: &action_steps [{ uses: actions/checkout@v4 }]
""",
                "dotted-anchor": """name: Synthetic dotted anchor
on: push
env: &.defaults
  FOO: bar
jobs:
  test:
    runs-on: ubuntu-latest
    env: *.defaults
    steps:
      - run: echo "$FOO"
""",
            }
            for shape, body in shapes.items():
                with self.subTest(shape=shape):
                    workflow.write_text(body, encoding="utf-8")
                    with self.assertRaisesRegex(
                        ValueError,
                        "explicit YAML mapping keys|escaped double-quoted YAML mapping keys|flow-style YAML containers|flow-style sequence items|flow-style steps lists|flow-style uses keys|uses values must stay on one line|YAML anchors|YAML node tags",
                    ):
                        list(uses_records(workflow))
                    result = subprocess.run(
                        [BASH, "scripts/smoke.sh"],
                        cwd=output,
                        check=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertRegex(
                        result.stdout,
                        r"flow-style YAML containers|flow-style sequence items|flow-style steps lists|flow-style uses keys|uses values must stay on one line|explicit YAML mapping keys|escaped double-quoted YAML mapping keys|YAML anchors|YAML node tags",
                    )
                    self.assertNotIn("actions/checkout@v4", result.stdout)

    def test_comment_cannot_open_a_fake_scalar_and_hide_a_floating_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "project"
            subprocess.run(
                [
                    "python3",
                    str(ROOT / "bin" / "generate.py"),
                    "--values",
                    str(ROOT / "examples" / "chrome-extension.answers.json"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            workflow = output / ".github" / "workflows" / "comment-scalar.yml"
            bodies = {
                "full-line": """name: Rock, 'n roll
description: Hello,'unreviewed
summary: Status['unreviewed] State{'unreviewed}
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    # scanner: |
      - uses: actions/checkout@v4
""",
                "plain-continuation": """name: This remains
  'plain text
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
                "sequence-plain-continuation": """name: Sequence continuation
on:
  workflow_dispatch:
    inputs:
      mode:
        type: choice
        options:
          - safe
            'plain choice
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
                "closed-flow-punctuation": """name: Status]:'unreviewed
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
                "inline": """name: Synthetic inline comment scalar
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps: # scanner: |
      - uses: actions/checkout@v4
""",
                "quoted-comment": """name: Synthetic quoted comment
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: "scanner: | # note"
        uses: actions/checkout@v4
""",
                "compact-sequence": """name: Synthetic compact sequence scalar
on: workflow_dispatch
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: |
          Checkout
        uses: actions/checkout@v4
""",
            }
            for shape, body in bodies.items():
                with self.subTest(shape=shape):
                    workflow.write_text(body, encoding="utf-8")
                    records = list(uses_records(workflow))
                    self.assertEqual(records[0][1], "actions/checkout@v4")
                    result = subprocess.run(
                        [BASH, "scripts/smoke.sh"],
                        cwd=output,
                        check=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn("action ref pin", result.stdout)
                    self.assertNotIn("actions/checkout@v4", result.stdout)

    def test_explicit_scalar_indentation_keeps_body_text_inert(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "project"
            subprocess.run(
                [
                    "python3",
                    str(ROOT / "bin" / "generate.py"),
                    "--values",
                    str(ROOT / "examples" / "chrome-extension.answers.json"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            workflow = output / ".github" / "workflows" / "explicit-scalar.yml"
            workflow.write_text(
                """name: Don't hide actions
description: "Synthetic *release
  { uses: actions/checkout@v4 }"
on: workflow_dispatch
env: { FOO: bar, NOTE: 'text "\\u0075ses": harmless' }
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - shell: bash
        run: |2
            cat <<'EOF'
          uses: actions/checkout@v4
          EOF
""",
                encoding="utf-8",
            )
            self.assertEqual(list(uses_records(workflow)), [])
            result = subprocess.run(
                [BASH, "scripts/smoke.sh"],
                cwd=output,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
