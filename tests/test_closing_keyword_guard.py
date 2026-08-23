"""Adversarial contract for issue-closing intent in commits and pull requests."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "check-closing-keywords.sh"
BASH = os.environ.get("CLOSING_GUARD_SHELL", "sh")


def workflow_document(workflow: str) -> dict:
    document = yaml.load(workflow, Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def named_step(document: dict, name: str) -> dict:
    jobs = document.get("jobs")
    assert isinstance(jobs, dict)
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert isinstance(job, dict)
    steps = job.get("steps")
    assert isinstance(steps, list)
    matches = [step for step in steps if isinstance(step, dict) and step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def assert_commit_workflow_contract(workflow: str, checker: str) -> None:
    document = workflow_document(workflow)
    triggers = document["on"]["pull_request"]
    assert triggers["types"] == [
        "opened",
        "reopened",
        "synchronize",
        "edited",
        "labeled",
        "ready_for_review",
    ]
    assert document["permissions"] == {"contents": "read"}
    trusted = named_step(document, "Checkout trusted guard")
    candidate = named_step(document, "Checkout candidate history as data")
    validation = named_step(
        document, "Validate issue-closing intent and commit subjects"
    )
    assert trusted["with"] == {
        "ref": "${{ github.event.repository.default_branch }}",
        "path": "trusted-base",
        "fetch-depth": "1",
        "persist-credentials": "false",
    }
    assert candidate["with"] == {
        "ref": "${{ github.event.pull_request.head.sha }}",
        "path": "candidate-history",
        "fetch-depth": "0",
        "persist-credentials": "false",
    }
    assert validation["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert validation["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    active = validation["run"]
    assert f'CHECKER="$GITHUB_WORKSPACE/trusted-base/{checker}"' in active
    assert 'COMMIT_REPO="$GITHUB_WORKSPACE/candidate-history"' in active
    assert 'cd "$COMMIT_REPO"' in active
    assert 'sh "$CHECKER"' in active
    assert "--commit-range" in active
    assert "--pr-title-file" in active
    assert "--pr-body-file" in active
    assert "github.base_ref" not in workflow
    jobs = document["jobs"]
    assert next(iter(jobs.values()))["name"] == "Conventional Commits"


def assert_auto_merge_contract(workflow: str, checker: str) -> None:
    document = workflow_document(workflow)
    triggers = document["on"]
    assert "pull_request" not in triggers
    assert triggers["check_suite"]["types"] == ["completed"]
    assert "Commit Lint" in triggers["workflow_run"]["workflows"]
    trusted = named_step(document, "Checkout trusted closing-intent guard")
    final_step = named_step(document, "Revalidate fresh closing intent and squash-merge")
    assert trusted["with"] == {
        "ref": "${{ github.event.repository.default_branch }}",
        "path": "trusted-base",
        "fetch-depth": "1",
        "persist-credentials": "false",
    }
    script = final_step["with"]["script"]
    component_cursor = 0
    for component in ("trusted-base", *checker.split("/")):
        component_cursor = script.index(f"'{component}'", component_cursor) + 1
    fresh = script.index("github.rest.pulls.get")
    guard = script.index("--pr-title-file", fresh)
    merge = script.index("github.rest.pulls.merge")
    assert fresh < guard < merge
    merge_block = script[merge:]
    assert "commit_title: pr.title" in merge_block
    assert "commit_message: 'Squash-merged after required checks" in merge_block
    assert "pr.head.sha !== expectedSha" in script[fresh:guard]
    assert "Merged PR #${" not in workflow


class ClosingKeywordBehaviorTests(unittest.TestCase):
    def run_file(self, option: str, content: str | bytes) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "private-input"
            if isinstance(content, bytes):
                fixture.write_bytes(content)
            else:
                fixture.write_text(content, encoding="utf-8")
            return subprocess.run(
                [BASH, str(SCRIPT), option, str(fixture)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def assert_rejected(self, option: str, content: str | bytes) -> None:
        result = self.run_file(option, content)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        for private_fragment in ("private-input", "sample-owner", "sample-repo", "#98765"):
            self.assertNotIn(private_fragment, output)

    def assert_allowed(self, option: str, content: str | bytes) -> None:
        result = self.run_file(option, content)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "closing-keyword guard: PASS")

    def test_full_commit_messages_reject_every_keyword_shape_and_commit_type(self) -> None:
        rejected = (
            "Fix #98765",
            "feat: safe subject\n\nCloses: #98765",
            "Revert safe change\n\nFIXED #98765",
            "Merge branch safely\n\nresolveS: sample-owner/sample-repo#98765",
            "fixup! feat: safe\n\nclose #98765",
            "squash! feat: safe\n\nclosed: #98765",
            "feat: safe\n\nFixes [#98765](https://example.invalid)",
            "feat: safe\n\nFixes `#98765`",
            "feat: safe\n\nFixes https://github.com/sample-owner/sample-repo/issues/98765",
        )
        for message in rejected:
            with self.subTest(message=message.splitlines()[0]):
                self.assert_rejected("--commit-file", message)

    def test_non_directive_numbered_prose_and_bare_references_are_allowed(self) -> None:
        allowed = (
            "fix(parser): fix numbered parsing",
            "feat: safe\n\nFix 1 before Fix 2.",
            "feat: safe\n\nFixes issue 1.",
            "feat: safe\n\nFixes # 1.",
            "feat: safe\n\nhotfixes #98765 remain ordinary prose.",
            "feat: safe\n\nThis fixes parsing for reference #98765.",
            "feat: safe\n\nSee #98765 and https://github.com/sample-owner/sample-repo/issues/98765.",
        )
        for message in allowed:
            with self.subTest(message=message):
                self.assert_allowed("--commit-file", message)

    def test_pr_titles_reject_closers_but_allow_normal_fix_prose(self) -> None:
        self.assert_rejected("--pr-title-file", "fix(parser): Fixes #98765")
        self.assert_rejected(
            "--pr-title-file", "fix(parser): RESOLVED: sample-owner/sample-repo#98765"
        )
        self.assert_allowed(
            "--pr-title-file", "fix(parser): fixes parsing for reference #98765"
        )

    def test_canonical_pr_body_accepts_none_or_deduplicated_targets(self) -> None:
        self.assert_allowed("--pr-body-file", "## Issue closure\n\nNone\n")
        self.assert_allowed(
            "--pr-body-file",
            "## Summary\nSafe change.\n\n## Issue closure\n\n"
            "Closes: #123\nCloses: Example-Org/sample.repo#456\n",
        )
        self.assert_allowed(
            "--pr-body-file",
            b"## Summary\r\nSafe change.\r\n\r\n## Issue closure\r\n\r\nCloses: #123\r\n",
        )

    def test_pr_body_rejects_directives_in_every_markdown_context(self) -> None:
        contexts = (
            "Fixes #98765",
            "> Fixes #98765",
            "`Fixes #98765`",
            "```text\nFixes #98765\n```",
            "<!-- Fixes #98765 -->",
            "Fixes [#98765](https://example.invalid)",
            "Fixes **#98765**",
            "Fixes https://github.com/sample-owner/sample-repo/issues/98765",
            "A quote says \"FIXED: sample-owner/sample-repo#98765\".",
        )
        for prose in contexts:
            with self.subTest(prose=prose):
                self.assert_rejected(
                    "--pr-body-file",
                    f"## Summary\n{prose}\n\n## Issue closure\n\nNone\n",
                )

    def test_pr_body_rejects_noncanonical_or_ambiguous_sections(self) -> None:
        rejected = (
            "## Summary\nNo final section.\n",
            "## Issue closure\nNone\n",
            "## Issue closure\n\nNone\nCloses: #2\n",
            "## Issue closure\n\ncloses: #2\n",
            "## Issue closure\n\nCloses #2\n",
            "## Issue closure\n\nCloses: #02\n",
            "## Issue closure\n\nCloses: #2, #3\n",
            "## Issue closure\n\nCloses: [#2](https://example.invalid)\n",
            "## Issue closure\n\nCloses: https://github.com/o/r/issues/2\n",
            "## Issue closure\n\nCloses: ../repo#2\n",
            "## Issue closure\n\nCloses: -owner/repo#2\n",
            "## Issue closure\n\nCloses: owner-/repo#2\n",
            "## Issue closure\n\nCloses: owner--name/repo#2\n",
            "## Issue closure\n\nCloses: owner/..#2\n",
            "## Issue closure\n\nCloses: öwner/repo#2\n",
            "## Issue closure\n\nCloses: #2\nCloses: #2\n",
            "## Issue closure\n\nCloses: Example/Repo#2\nCloses: example/repo#2\n",
            "## Issue closure\n\nNone\n\nTrailing prose.\n",
            "## Issue closure\n\nNone\n\n## Issue closure\n\nNone\n",
        )
        for body in rejected:
            with self.subTest(body=body):
                self.assert_rejected("--pr-body-file", body)

    def test_commit_range_uses_full_bodies_and_excludes_the_base_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Contract Test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "contract@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "--allow-empty", "-q", "-m", "Fixes #91"],
                cwd=repo,
                check=True,
            )
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            subprocess.run(
                ["git", "commit", "--allow-empty", "-q", "-m", "feat: safe subject"],
                cwd=repo,
                check=True,
            )
            safe_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            safe = subprocess.run(
                [BASH, str(SCRIPT), "--commit-range", f"{base}..{safe_head}"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(safe.returncode, 0, safe.stdout + safe.stderr)

            private_tmp = repo / "PRIVATE-LEAK-98765" / "missing"
            bad_tmp_env = os.environ.copy()
            bad_tmp_env["TMPDIR"] = str(private_tmp)
            bad_tmp = subprocess.run(
                [BASH, str(SCRIPT), "--commit-range", f"{base}..{safe_head}"],
                cwd=repo,
                env=bad_tmp_env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(bad_tmp.returncode, 2, bad_tmp.stdout + bad_tmp.stderr)
            self.assertNotIn("PRIVATE-LEAK-98765", bad_tmp.stdout + bad_tmp.stderr)
            self.assertNotIn(str(private_tmp), bad_tmp.stdout + bad_tmp.stderr)

            noisy_bin = repo / "noisy-bin"
            noisy_bin.mkdir()
            fake_rm = noisy_bin / "rm"
            fake_rm.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'PRIVATE-LEAK-98765'\n"
                "printf '%s\\n' 'PRIVATE-LEAK-98765' >&2\n"
                "exit 2\n",
                encoding="utf-8",
            )
            fake_rm.chmod(0o755)
            noisy_rm_env = os.environ.copy()
            noisy_rm_env["PATH"] = f"{noisy_bin}{os.pathsep}{noisy_rm_env['PATH']}"
            noisy_cleanup = subprocess.run(
                [BASH, str(SCRIPT), "--commit-range", f"{base}..{safe_head}"],
                cwd=repo,
                env=noisy_rm_env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                noisy_cleanup.returncode,
                2,
                noisy_cleanup.stdout + noisy_cleanup.stderr,
            )
            self.assertNotIn(
                "PRIVATE-LEAK-98765", noisy_cleanup.stdout + noisy_cleanup.stderr
            )

            no_op_bin = repo / "no-op-bin"
            no_op_bin.mkdir()
            no_op_rm = no_op_bin / "rm"
            no_op_rm.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            no_op_rm.chmod(0o755)
            private_temp = repo / "private-temp"
            private_temp.mkdir()
            no_op_env = os.environ.copy()
            no_op_env["PATH"] = f"{no_op_bin}{os.pathsep}{no_op_env['PATH']}"
            no_op_env["TMPDIR"] = str(private_temp)
            no_op_cleanup = subprocess.run(
                [BASH, str(SCRIPT), "--commit-range", f"{base}..{safe_head}"],
                cwd=repo,
                env=no_op_env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                no_op_cleanup.returncode,
                2,
                no_op_cleanup.stdout + no_op_cleanup.stderr,
            )
            self.assertNotIn(str(private_temp), no_op_cleanup.stdout + no_op_cleanup.stderr)
            leftovers = list(private_temp.iterdir())
            self.assertEqual(len(leftovers), 1)
            leftovers[0].unlink()

            subprocess.run(
                [
                    "git",
                    "commit",
                    "--allow-empty",
                    "-q",
                    "-m",
                    "feat: safe subject",
                    "-m",
                    "FIXED: sample-owner/sample-repo#98765",
                ],
                cwd=repo,
                check=True,
            )
            unsafe_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            unsafe = subprocess.run(
                [BASH, str(SCRIPT), "--commit-range", f"{safe_head}..{unsafe_head}"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(unsafe.returncode, 1, unsafe.stdout + unsafe.stderr)
            for private_fragment in (
                unsafe_head,
                "sample-owner",
                "sample-repo",
                "#98765",
                str(repo),
            ):
                self.assertNotIn(private_fragment, unsafe.stdout + unsafe.stderr)

            earlier_base = unsafe_head
            subprocess.run(
                [
                    "git",
                    "commit",
                    "--allow-empty",
                    "-q",
                    "-m",
                    "feat: safe subject",
                    "-m",
                    "Closes: #98765",
                ],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "--allow-empty", "-q", "-m", "feat: safe head"],
                cwd=repo,
                check=True,
            )
            safe_final_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            earlier_unsafe = subprocess.run(
                [BASH, str(SCRIPT), "--commit-range", f"{earlier_base}..{safe_final_head}"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                earlier_unsafe.returncode,
                1,
                earlier_unsafe.stdout + earlier_unsafe.stderr,
            )

    def test_analyzer_failures_are_content_suppressed_and_fail_closed(self) -> None:
        shell = shutil.which(BASH)
        self.assertIsNotNone(shell)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "private-input"
            fixture.write_text("Fixes #98765", encoding="utf-8")
            empty_bin = root / "empty-bin"
            empty_bin.mkdir()
            missing_env = os.environ.copy()
            missing_env["PATH"] = str(empty_bin)
            for option in ("--commit-file", "--pr-title-file", "--pr-body-file"):
                result = subprocess.run(
                    [str(shell), str(SCRIPT), option, str(fixture)],
                    cwd=ROOT,
                    env=missing_env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                output = result.stdout + result.stderr
                self.assertNotIn(str(fixture), output)
                self.assertNotIn("#98765", output)

            noisy_bin = root / "noisy-bin"
            noisy_bin.mkdir()
            fake_awk = noisy_bin / "awk"
            fake_awk.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'PRIVATE-LEAK-98765 sample-owner/sample-repo#98765'\n"
                "printf '%s\\n' 'PRIVATE-LEAK-98765 sample-owner/sample-repo#98765' >&2\n"
                "exit 2\n",
                encoding="utf-8",
            )
            fake_awk.chmod(0o755)
            noisy_env = os.environ.copy()
            noisy_env["PATH"] = f"{noisy_bin}{os.pathsep}{noisy_env['PATH']}"
            for option in ("--commit-file", "--pr-title-file", "--pr-body-file"):
                result = subprocess.run(
                    [str(shell), str(SCRIPT), option, str(fixture)],
                    cwd=ROOT,
                    env=noisy_env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                for private_fragment in (
                    str(fixture),
                    "PRIVATE-LEAK-98765",
                    "sample-owner",
                    "sample-repo",
                    "#98765",
                ):
                    self.assertNotIn(private_fragment, result.stdout + result.stderr)

            disappearing_bin = root / "disappearing-bin"
            disappearing_bin.mkdir()
            disappearing_awk = disappearing_bin / "awk"
            disappearing_awk.write_text(
                "#!/bin/sh\n"
                "for argument do target=$argument; done\n"
                "/bin/rm -f -- \"$target\"\n"
                "printf '%s\\n' 'sample-owner/sample-repo#98765' >&2\n"
                "exit 2\n",
                encoding="utf-8",
            )
            disappearing_awk.chmod(0o755)
            disappearing_env = os.environ.copy()
            disappearing_env["PATH"] = (
                f"{disappearing_bin}{os.pathsep}{disappearing_env['PATH']}"
            )
            fixture.write_text("Fixes #98765", encoding="utf-8")
            disappeared = subprocess.run(
                [str(shell), str(SCRIPT), "--pr-title-file", str(fixture)],
                cwd=ROOT,
                env=disappearing_env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                disappeared.returncode,
                2,
                disappeared.stdout + disappeared.stderr,
            )
            for private_fragment in (str(fixture), "sample-owner", "#98765"):
                self.assertNotIn(
                    private_fragment, disappeared.stdout + disappeared.stderr
                )


class ClosingKeywordWiringTests(unittest.TestCase):
    def test_hook_checks_full_message_before_subject_skip(self) -> None:
        hook = (ROOT / "template" / ".githooks" / "commit-msg").read_text(
            encoding="utf-8"
        )
        guard = hook.index("--commit-file")
        skip = hook.index('case "$SUBJECT"')
        self.assertLess(guard, skip)
        self.assertIn('"$MSG_FILE"', hook)
        self.assertNotIn("strip-comments", hook)

        shell = shutil.which(BASH)
        self.assertIsNotNone(shell)
        with tempfile.TemporaryDirectory() as tmp:
            repository = Path(tmp) / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            message = repository / "message"
            message.write_text(
                "feat: safe subject\n\nOrdinary rationale.\n",
                encoding="utf-8",
            )
            safe = subprocess.run(
                [str(shell), str(ROOT / "template" / ".githooks" / "commit-msg"), str(message)],
                cwd=repository,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(safe.returncode, 0, safe.stdout + safe.stderr)
            message.write_text(
                "feat: safe subject\n\n# Fix #98765 may be retained by Git.\n",
                encoding="utf-8",
            )
            unsafe = subprocess.run(
                [str(shell), str(ROOT / "template" / ".githooks" / "commit-msg"), str(message)],
                cwd=repository,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(unsafe.returncode, 1, unsafe.stdout + unsafe.stderr)
            self.assertNotIn("#98765", unsafe.stdout + unsafe.stderr)

            hooks = repository / ".hooks"
            hooks.mkdir()
            wrapper = hooks / "commit-msg"
            wrapper.write_text(
                "#!/bin/sh\nexec sh "
                + shlex.quote(str(ROOT / "template" / ".githooks" / "commit-msg"))
                + ' "$@"\n',
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            subprocess.run(
                ["git", "config", "user.name", "Contract Test"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "contract@example.invalid"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "core.hooksPath", str(hooks)],
                cwd=repository,
                check=True,
            )
            committed = subprocess.run(
                ["git", "commit", "--allow-empty", "-q", "-m", "feat: safe subject"],
                cwd=repository,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
            unsafe_m = subprocess.run(
                [
                    "git",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "feat: safe subject",
                    "-m",
                    "# Fixes #98765",
                ],
                cwd=repository,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(unsafe_m.returncode, 0)
            self.assertNotIn("#98765", unsafe_m.stdout + unsafe_m.stderr)
            message.write_text(
                "feat: safe subject\n\n# Fixes #98765\n", encoding="utf-8"
            )
            unsafe_verbatim = subprocess.run(
                [
                    "git",
                    "-c",
                    "commit.cleanup=verbatim",
                    "commit",
                    "--allow-empty",
                    "-F",
                    str(message),
                ],
                cwd=repository,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(unsafe_verbatim.returncode, 0)
            self.assertNotIn("#98765", unsafe_verbatim.stdout + unsafe_verbatim.stderr)

    def test_commit_lint_uses_exact_event_range_and_metadata_edit_events(self) -> None:
        for relative, checker in (
            (Path(".github/workflows/commit-lint.yml"), "template/scripts/check-closing-keywords.sh"),
            (
                Path("template/.github/workflows/commit-lint.yml"),
                "scripts/check-closing-keywords.sh",
            ),
        ):
            workflow = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(workflow=relative):
                assert_commit_workflow_contract(workflow, checker)
                mutations = (
                    workflow.replace(", edited", "", 1),
                    workflow.replace(", labeled", "", 1),
                    workflow.replace("contents: read", "contents: write", 1),
                    workflow.replace("persist-credentials: false", "persist-credentials: true", 1),
                    workflow.replace(
                        "path: candidate-history\n          fetch-depth: 0\n          persist-credentials: false",
                        "path: candidate-history\n          fetch-depth: 0\n          persist-credentials: true",
                        1,
                    ),
                    workflow.replace(
                        f"trusted-base/{checker}", f"candidate-history/{checker}", 1
                    ),
                    workflow.replace(
                        "ref: ${{ github.event.repository.default_branch }}",
                        "ref: ${{ github.event.pull_request.head.sha }}",
                        1,
                    )
                    + "\n# ref: ${{ github.event.repository.default_branch }}\n",
                )
                for mutation in mutations:
                    with self.assertRaises(AssertionError):
                        assert_commit_workflow_contract(mutation, checker)

    def test_auto_merge_uses_trusted_parser_fresh_metadata_and_safe_squash_text(self) -> None:
        for relative, checker in (
            (
                Path(".github/workflows/auto-merge.yml"),
                "template/scripts/check-closing-keywords.sh",
            ),
            (
                Path("template/.github/workflows/auto-merge.yml"),
                "scripts/check-closing-keywords.sh",
            ),
        ):
            workflow = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(workflow=relative):
                assert_auto_merge_contract(workflow, checker)
                mutations = (
                    workflow.replace(
                        "on:\n  check_suite:",
                        "on:\n  pull_request:\n    types: [edited]\n  check_suite:",
                        1,
                    ),
                    workflow.replace('workflows: [CI, "Commit Lint", "AI PR Review"]', 'workflows: [CI, "AI PR Review"]', 1),
                    workflow.replace(
                        "ref: ${{ github.event.repository.default_branch }}",
                        "ref: ${{ github.event.pull_request.head.sha }}",
                        1,
                    )
                    + "\n# ref: ${{ github.event.repository.default_branch }}\n",
                    workflow.replace("persist-credentials: false", "persist-credentials: true", 1),
                    workflow.replace("'trusted-base'", "'candidate-history'", 1),
                    workflow.replace("github.rest.pulls.get", "github.rest.issues.get", 1),
                    workflow.replace("commit_title: pr.title,", "", 1),
                    workflow.replace(
                        "commit_message: 'Squash-merged after required checks and issue-closing intent validation.',",
                        "",
                        1,
                    ),
                    workflow.replace(
                        "const { data: pr } = await github.rest.pulls.get",
                        "await github.rest.pulls.merge({});\n            const { data: pr } = await github.rest.pulls.get",
                        1,
                    ),
                    workflow
                    + "\n  unexpected-merge:\n"
                    + "    runs-on: ubuntu-latest\n"
                    + "    steps:\n"
                    + "      - run: echo github.rest.pulls.merge\n",
                )
                for mutation in mutations:
                    with self.assertRaises((AssertionError, ValueError, KeyError)):
                        assert_auto_merge_contract(mutation, checker)

    def test_parser_keeps_mutation_sensitive_contract_fragments(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        required = (
            "git show -s --format=%B",
            "close[sd]?|fix(es|ed)?|resolve[sd]?",
            "## Issue closure",
            "valid_target(target)",
            "length(owner) > 39",
            "seen[target]++",
            "sub(/\\r$/, \"\")",
            "--commit-range",
            "--pr-title-file",
            "--pr-body-file",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_every_declared_stack_stamps_the_complete_guard(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for answers in sorted((ROOT / "examples").glob("*.answers.json")):
                stack = answers.name.removesuffix(".answers.json")
                output = root / stack
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
                generated = output / "scripts" / "check-closing-keywords.sh"
                self.assertEqual(generated.read_text(encoding="utf-8"), source)
                self.assertTrue(generated.stat().st_mode & stat.S_IXUSR)
                self.assertIn(
                    "--commit-file",
                    (output / ".githooks" / "commit-msg").read_text(encoding="utf-8"),
                )
                self.assertIn(
                    "--pr-body-file",
                    (output / ".github" / "workflows" / "commit-lint.yml").read_text(encoding="utf-8"),
                )
                assert_commit_workflow_contract(
                    (output / ".github" / "workflows" / "commit-lint.yml").read_text(
                        encoding="utf-8"
                    ),
                    "scripts/check-closing-keywords.sh",
                )
                assert_auto_merge_contract(
                    (output / ".github" / "workflows" / "auto-merge.yml").read_text(
                        encoding="utf-8"
                    ),
                    "scripts/check-closing-keywords.sh",
                )
                self.assertTrue(
                    (output / ".github" / "pull_request_template.md")
                    .read_text(encoding="utf-8")
                    .rstrip()
                    .endswith("## Issue closure\n\nNone")
                )


if __name__ == "__main__":
    unittest.main()
