"""Adversarial contract for the dependency-free documentation preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "check-docs.sh"
BASH = os.environ.get("DOC_CHECK_BASH", "bash")


class DocIntegrityBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name) / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPT, self.repo / "scripts" / "check-docs.sh")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        self.seed_house_docs()

    def write(self, relative: str, body: str) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def seed_house_docs(self) -> None:
        self.write("VERSION", "0.1.0\n")
        self.write(
            "CHANGELOG.md",
            "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - YYYY-MM-DD\n",
        )
        for path, heading in (
            ("README.md", "Project"),
            ("SECURITY.md", "Security"),
            ("CONTRIBUTING.md", "Contributing"),
            ("ARCHITECTURE.md", "Architecture"),
            ("AGENTS.md", "Agents"),
            ("CLAUDE.md", "Claude"),
            ("docs/LOCAL_TLS.md", "Local TLS"),
            ("docs/DEPLOY_POLICY.md", "Deploy policy"),
            ("docs/PRACTICES.md", "Practices"),
            ("docs/SECURITY_INCIDENT_ROTATION.md", "Security incident rotation"),
            ("docs/STORYBOARD.md", "Storyboard"),
            ("docs/FEATURE_HANDOFF.md", "Feature handoff"),
            ("docs/storyboard-harness.md", "Storyboard harness"),
        ):
            self.write(path, f"# {heading}\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)

    def run_check(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, "scripts/check-docs.sh", *args],
            cwd=self.repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "LC_ALL": "C"},
        )

    @staticmethod
    def combined(result: subprocess.CompletedProcess[str]) -> str:
        return result.stdout + result.stderr

    def test_safe_inline_reference_and_mermaid_forms_pass(self) -> None:
        self.write("docs/guide (v1).md", "# Guide\n")
        self.write("docs/guide(v2).md", "# Guide v2\n")
        self.write(
            "README.md",
            r"""# Project

[guide](<docs/guide (v1).md#guide>)
[escaped](docs/guide\(v2\).md)
[security](SECURITY.md)
[external](https://example.test/path)
[escaped external](https\://example.test/path)
[same page](#project)
[reference][guide-ref]
[guide-ref]: docs/guide%20(v1).md
`[code sample](missing-private-path.md)`

```mermaid
sequenceDiagram
    A->>B: visible semicolon is #59; encoded
```
""",
        )
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)

        result = self.run_check()
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertRegex(
            result.stdout, r"mode=working docs=\d+ local-links=4 mermaid=1"
        )

    def test_embedded_resources_must_be_files_while_directory_links_are_valid(self) -> None:
        self.write("docs/assets/frame.png", "synthetic image bytes\n")
        self.write(
            "README.md",
            """# Project

[asset directory](docs/assets)
![invalid direct image](docs/assets)
![invalid reference image][asset-dir]
[asset-dir]: docs/assets
[![nested missing image](docs/assets/missing.png)](docs/assets)
![fragment is not an image](#preview)
![query is not an image](?raw=1)
![query reference is not an image][asset-query]
[asset-query]: ?raw=1
<img src="?raw=1">
""",
        )
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)

        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertGreaterEqual(
            self.combined(result).count("embedded local resource must resolve"), 7
        )

    def test_missing_escape_and_untracked_targets_fail_without_path_disclosure(self) -> None:
        private_target = "unguessable-private-review-path.md"
        self.write(
            "README.md",
            (
                f"# Project\n\n[missing]({private_target})\n"
                "[escape](../outside.md)\n[root](/SECURITY.md)\n"
                "[undefined][missing-reference]\n"
            ),
        )
        self.write("docs/untracked.md", "# Exists only in the working tree\n")
        with self.write("SECURITY.md", "# Security\n\n[untracked](docs/untracked.md)\n").open():
            pass

        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        combined = self.combined(result)
        self.assertIn("does not resolve to a regular publishable path", combined)
        self.assertIn("escapes the repository", combined)
        self.assertIn("site-root links are not portable", combined)
        self.assertIn("undefined normalized reference-link label", combined)
        self.assertNotIn(private_target, combined)
        self.assertNotIn("untracked.md", combined)

    def test_staged_mode_is_immutable_and_working_mode_includes_untracked(self) -> None:
        self.write("docs/good.md", "# Good\n")
        self.write("README.md", "# Project\n\n[bad](docs/missing.md)\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        self.write("README.md", "# Project\n\n[good](docs/good.md)\n")

        staged = self.run_check("--staged")
        working = self.run_check()
        self.assertEqual(staged.returncode, 1)
        self.assertEqual(working.returncode, 0, self.combined(working))
        self.assertIn("mode=working", working.stdout)

        checker = self.repo / "scripts" / "check-docs.sh"
        checker.write_text(checker.read_text() + "\n# unstaged drift\n")
        drifted = self.run_check("--staged")
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("differs from the staged checker", self.combined(drifted))

    def test_ignored_case_mismatch_symlink_and_encoded_escape_fail(self) -> None:
        self.write("docs/Actual.md", "# Actual\n")
        self.write("docs/ignored.md", "# Ignored\n")
        self.write(".gitignore", "docs/ignored.md\n")
        (self.repo / "docs" / "linked.md").symlink_to("Actual.md")
        self.write(
            "README.md",
            """# Project

[case](docs/actual.md)
[ignored](docs/ignored.md)
[symlink](docs/linked.md)
[encoded escape](%2e%2e%2foutside.md)
[encoded site root](%2fSECURITY.md)
[Windows drive path](C:/SECURITY.md)
""",
        )
        subprocess.run(
            ["git", "add", "README.md", ".gitignore", "docs/Actual.md"],
            cwd=self.repo,
            check=True,
        )

        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        combined = self.combined(result)
        self.assertGreaterEqual(
            combined.count("does not resolve to a regular publishable path"), 3
        )
        self.assertIn("escapes the repository", combined)
        self.assertIn("site-root links are not portable", combined)
        self.assertIn("must not use Windows drive paths", combined)

    def test_html_assets_and_privacy_safe_diagnostics(self) -> None:
        signed = "https://example.test/asset?token=secret-shaped-value"
        self.write("docs/preview(v2).png", "synthetic image bytes\n")
        self.write(
            "README.md",
            f'<img src="docs/missing-preview.png">\n'
            '<img src="docs/preview\\(v2\\).png">\n'
            f'<a href="{signed}">review</a>\n',
        )
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        combined = self.combined(result)
        self.assertIn("embedded local resource must resolve", combined)
        self.assertIn("portable forward slashes", combined)
        self.assertNotIn("missing-preview", combined)
        self.assertNotIn("secret-shaped-value", combined)

    def test_mermaid_allowlist_empty_unclosed_and_literal_semicolon_fail(self) -> None:
        private_mermaid = "PRIVATE_SIGNING_KEY_SHOULD_NOT_APPEAR"
        self.write(
            "README.md",
            f"""# Project

```mermaid
madeUpDiagram {private_mermaid}
```

```mermaid
```

```mermaid
sequenceDiagram
    A->>B: first statement; B->>A: ambiguous second statement
```

```text
never closed
""",
        )

        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        combined = self.combined(result)
        self.assertIn("allowlisted diagram type", combined)
        self.assertIn("empty Mermaid fence", combined)
        self.assertIn("literal semicolon in sequenceDiagram", combined)
        self.assertIn("unclosed fenced code block", combined)
        self.assertNotIn(private_mermaid, combined)

    def test_mermaid_prefixes_crlf_and_nonsequence_semicolons_pass(self) -> None:
        self.write(
            "README.md",
            """# Project\r
\r
```mermaid\r
---\r
title: Synthetic\r
---\r
%% leading comment; ignored\r
%%{init: {'theme': 'neutral'}}%%\r
flowchart LR\r
    A --> B;\r
```\r
\r
```mermaid\r
info\r
```\r
""",
        )
        self.write(
            "CHANGELOG.md",
            "# Changelog\r\n\r\n## [Unreleased]\r\n\r\n"
            "## [0.1.0] - YYYY-MM-DD\r\n",
        )
        result = self.run_check()
        self.assertEqual(result.returncode, 0, self.combined(result))

    def test_release_heading_tracks_version_and_placeholder_is_seed_only(self) -> None:
        self.write("VERSION", "0.2.0\n")
        self.write(
            "CHANGELOG.md",
            "# Changelog\n\n## [Unreleased]\n\n## [0.2.0] - YYYY-MM-DD\n",
        )
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("placeholder is valid only", self.combined(result))

        self.write(
            "CHANGELOG.md",
            "# Changelog\n\n## [Unreleased]\n\n## [0.2.0] - 2026-08-23\n",
        )
        result = self.run_check()
        self.assertEqual(result.returncode, 0, self.combined(result))

        self.write(
            "CHANGELOG.md",
            "# Changelog\n\n## [Unreleased]\n\n## [0.2.0] - 2026-02-30\n",
        )
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("valid ISO date", self.combined(result))


class DocIntegrityGeneratorTests(unittest.TestCase):
    @staticmethod
    def generate_and_check(output: Path, answers: Path, *settings: str) -> None:
        command = [
            "python3",
            str(ROOT / "bin" / "generate.py"),
            "--values",
            str(answers),
        ]
        for setting in settings:
            command.extend(("--set", setting))
        command.extend(("--output", str(output)))
        subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "init", "-q"], cwd=output, check=True)
        subprocess.run(["git", "add", "-A"], cwd=output, check=True)
        result = subprocess.run(
            [BASH, "scripts/check-docs.sh", "--staged"],
            cwd=output,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise AssertionError(f"{answers.name} {settings}: {result.stdout}{result.stderr}")

    def test_every_stack_stamps_a_runnable_required_gate(self) -> None:
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
                    script = output / "scripts" / "check-docs.sh"
                    self.assertTrue(script.exists())
                    self.assertTrue(os.access(script, os.X_OK))
                    self.assertNotIn("{{", script.read_text(encoding="utf-8"))

                    makefile = (output / "Makefile").read_text(encoding="utf-8")
                    self.assertIn("docs-check:", makefile)
                    self.assertRegex(makefile, r"(?m)^smoke: docs-check")
                    hook = (output / ".githooks" / "pre-commit").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("bash scripts/check-docs.sh --staged", hook)

                    subprocess.run(["git", "init", "-q"], cwd=output, check=True)
                    subprocess.run(["git", "add", "-A"], cwd=output, check=True)
                    result = subprocess.run(
                        [BASH, "scripts/check-docs.sh"],
                        cwd=output,
                        check=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    self.assertEqual(
                        result.returncode,
                        0,
                        f"{answers.name}: {result.stdout}{result.stderr}",
                    )

    def test_every_optional_overlay_and_all_enabled_composition_stays_green(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text())
        flags = sorted(
            key
            for key, value in config.items()
            if key.startswith("include_") and value == ["no", "yes"]
        )
        with tempfile.TemporaryDirectory() as temp:
            for answers in sorted((ROOT / "examples").glob("*.answers.json")):
                for flag in flags:
                    with self.subTest(answers=answers.name, flag=flag):
                        output = Path(temp) / answers.stem / flag
                        self.generate_and_check(output, answers, f"{flag}=yes")

                with self.subTest(answers=answers.name, composition="all-enabled"):
                    output = Path(temp) / answers.stem / "all-enabled"
                    self.generate_and_check(
                        output, answers, *(f"{flag}=yes" for flag in flags)
                    )

    def test_ci_contract_docs_and_source_material_are_bounded(self) -> None:
        for stack in sorted(path for path in (ROOT / "stacks").iterdir() if path.is_dir()):
            workflow = (stack / ".github" / "workflows" / "ci.yml").read_text(
                encoding="utf-8"
            )
            tests_job = workflow.split("  lint:", 1)[0]
            self.assertIn("run: make smoke", tests_job, stack.name)

        combined = "\n".join(
            path.read_text(encoding="utf-8").lower()
            for path in (
                SCRIPT,
                ROOT / "template" / ".githooks" / "pre-commit",
                *(ROOT / "stacks").glob("*/Makefile"),
            )
        )
        for forbidden in (
            "source-private-health-project",
            "source-private-research-project",
            "source-private-domain",
            "private-provider-account-id",
            "private-provider-secret-name",
            "unguessable-review-path",
        ):
            self.assertNotIn(forbidden, combined)

        root_workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("tests.test_doc_integrity_contract", root_workflow)
        self.assertIn("DOC_CHECK_BASH=/bin/bash", root_workflow)


if __name__ == "__main__":
    unittest.main()
