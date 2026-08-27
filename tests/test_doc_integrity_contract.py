"""Adversarial contract for the dependency-free documentation preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "check-docs.sh"
BASH = os.environ.get("DOC_CHECK_BASH", "bash")
PLATFORM_PRECEPT_HEADING = "## 9. Split platform-locked gates without hiding them"
PLATFORM_PRECEPT_START = "<!-- platform-locked-gate-precept:start -->"
PLATFORM_PRECEPT_END = "<!-- platform-locked-gate-precept:end -->"
PLATFORM_HEADER_FIELDS = (
    "# omitted-target:",
    "# constraint:",
    "# shared-portable-target:",
    "# authoritative-platform-target:",
    "# evidence-location:",
    "# merge-control:",
)
PLATFORM_SECTION_REQUIREMENTS = (
    "slow, flaky, expensive, or currently failing is not platform-locked",
    "synthetic/test inputs and no production data or credentials",
    "Run it on the exact candidate",
    "the sole intentional difference",
    "A portable mock may add coverage, but it is never evidence that the real "
    "platform command ran",
    "**Tests** / **Lint & Typecheck** / **Build**",
    "machine-observable required check for the exact candidate",
    "open the PR as a draft",
    "confirm the `auto-merge` label is absent",
    "remove `auto-merge` too",
    "Evidence composes per dimension",
    "Local platform evidence never replaces or reclassifies the hosted portable "
    "result",
    "unexecuted—not green for that dimension",
    "does **not** relax the no-host-SDK rule",
    "grants no new native-toolchain exception",
    "narrowly scoped CI-only native lane",
    "separate owner decision outside this convention",
)
PLATFORM_AGENT_REQUIREMENTS = (
    "### Platform-locked gates are explicit, not skipped",
    "docs/ENGINEERING_CONVENTIONS.md#9-split-platform-locked-gates-without-"
    "hiding-them",
    "same repository-owned portable target",
    "not a machine-observable required check, open the PR as a draft",
    "keep `auto-merge` absent",
    "until exact-candidate evidence is attached and reviewed",
    "grants no new native-toolchain exception",
)
IRREVERSIBLE_PRECEPT_HEADING = (
    "### Irreversible external actions are preview-first (a precept)"
)
IRREVERSIBLE_PRECEPT_START = "<!-- irreversible-action-precept:start -->"
IRREVERSIBLE_PRECEPT_END = "<!-- irreversible-action-precept:end -->"
IRREVERSIBLE_AGENT_REQUIREMENTS = (
    "Code quality, merge authority, and side-effect authority are separate",
    "operation that spends money or makes an external change that cannot be "
    "reliably undone",
    "plan/dry-run by default",
    "A deploy stays in the self-authorized lane only when it is cost-neutral "
    "and mechanically reversible",
    "its audience and content class are already authorized",
    "not the first disclosure of private, regulated, or competitively "
    "sensitive material",
    "Infrastructure rollback cannot retract a disclosure",
    "Classify each deploy substep independently",
    "migrations, DNS/IAM, messages/webhooks, billing, and first disclosure may "
    "still be gated",
    "never grants authority for an owner-only action",
    "Preview the exact scope without making the change",
    "State the actor, target, environment, effect, inputs",
    "audience/content class, source state or quote revision",
    "source state or quote revision, quantity, all-in maximum spend, expiry",
    "rollback or compensation path using repository-safe identifiers",
    "Interactive agents say what they are about to do and wait before "
    "invoking, queueing, or spawning the action",
    "never infer consent from urgency, earlier discussion, or approval of a "
    "different action",
    "Require fresh, explicit confirmation bound to that preview",
    "A changed target, effect, amount, cap, input, or environment invalidates "
    "confirmation",
    "Blank, blanket, stale, or replayed confirmation fails closed",
    "the flag only arms execution; it is not consent",
    "a one-use authorization bound to the canonical scope, confirmer authority, "
    "state/quote revision, expiry, and spend cap",
    "Omitting either boundary must perform no external write",
    "The authorization is valid only for the same normalized scope executed "
    "by that "
    "invocation",
    "it is never reusable blanket consent",
    "The maximum total authorized spend binds currency, quantity, fees/tax, "
    "billing period, and any renewal commitment",
    "A stable idempotency key binds that same scope and is reused across "
    "reconciliation retries",
    "If neither exists, make at most one attempt, then reconcile or hand off "
    "to the owner",
    "An indeterminate outcome is reconciled before retry and is never "
    "auto-retried blind",
    "Journal intent before execution, then the observed outcome",
    "A durable, sanitized write-ahead intent must succeed before the provider "
    "call",
    "If the outcome cannot be durably appended after the call, report "
    "`indeterminate`, retain the same idempotency key, and reconcile before "
    "any retry",
    "Public or repository journals use random opaque operation IDs or keyed "
    "digests",
    "any provider-ID mapping belongs in an approved private store",
    "Never record credentials, private records, identities, production "
    "identifiers, payloads, or competitive details",
    "the default path is a true no-op",
    "unsafe invocations are rejected",
    "duplicate/replayed execution is safe",
    "journal/reconciliation failures cannot report success",
    "fail closed and use the `owner-action` hand-off above",
)
IRREVERSIBLE_AGENT_GLOBAL_REQUIREMENTS = (
    "deploys outside the self-authorized deploy-policy lane",
    "deploys outside its self-authorized lane",
)
IRREVERSIBLE_CLAUDE_REQUIREMENTS = (
    "Preview irreversible actions; never infer consent",
    "fresh one-use authorization bound to the exact scope",
    "all-in spend bounds and idempotent execution",
    "write sanitized intent before the provider call",
    "A flag only arms execution; it is not consent",
    "confirmation never grants missing owner authority",
    "deploys outside the self-authorized deploy-policy lane",
)
IRREVERSIBLE_DEPLOY_REQUIREMENTS = (
    "Execution safety is a separate boundary from deploy authorization",
    "A deploy may keep the self-authorized path only when it satisfies this "
    "policy, is cost-neutral and mechanically reversible",
    "its audience/content class is already authorized",
    "not a first disclosure of private, regulated, or competitively sensitive "
    "material",
    "Infrastructure rollback cannot retract a disclosure",
    "Classify every substep independently",
    "migrations, DNS/IAM, messages/webhooks, billing, and first disclosure may "
    "still be gated",
    "preview exact scope, obtain fresh scope-bound authorization, execute with "
    "bounds and replay safety, and record a sanitized outcome",
    "That authorization never grants authority for the owner-only actions "
    "listed below",
    "a representative non-production database",
    "production application remains a separately owner-gated action",
)
IRREVERSIBLE_AGENT_FORBIDDEN = (
    "owner-only — prod credentials, prod-DB migrations, deploys, billing",
    "owner-only actions in [docs/DEPLOY_POLICY.md](docs/DEPLOY_POLICY.md) "
    "(deploy, credentials",
)
IRREVERSIBLE_CLAUDE_FORBIDDEN = (
    "owner-gated side-effects (deploy, credentials, prod migrations, spend)",
)
IRREVERSIBLE_DEPLOY_FORBIDDEN = (
    "A reversible, cost-neutral deploy is exempt from this precept",
    "Infrastructure rollback makes publication reversible",
    "All deploy substeps are self-authorized",
)
ROLLBACK_HEADING = "# Rollback decision frame"
ROLLBACK_START = "<!-- rollback-decision-frame:start -->"
ROLLBACK_END = "<!-- rollback-decision-frame:end -->"
ROLLBACK_REQUIREMENTS = (
    "Rollback is a recovery decision, not execution authority",
    "Production database restores remain owner-gated",
    "pause only affected deploys, migrations, writers, and repair attempts",
    "Keep monitoring, containment, safety, and reconciliation workers running",
    "Preserve privacy-safe evidence",
    "Public or repository records use opaque identifiers",
    "two primary recovery lanes",
    "Promotion does not itself recover state",
    "Treat disclosure and downstream effects separately",
    "Neither lane retracts a disclosure",
    "the exact target artifact is immutable, provenance-verified",
    "reads and writes are proven against the current schema and data semantics",
    "permissions, jobs, and queued messages",
    "reviewed, bounded, production-safe probes that use synthetic identities",
    "Do not run a generic API/E2E suite against production",
    "must pass the preview-first irreversible-action gate",
    "Do not cycle between artifacts while compatibility or the live outcome is "
    "indeterminate",
    "expand/transition/contract migration",
    "current application with the current schema",
    "previous application with the current schema",
    "current application with the previous schema",
    "Dual-write is optional; when used, prove idempotency and convergence",
    "remove the old contract only after the rollback window closes",
    "no supported release depends on it",
    '"Additive" SQL can still break an older release',
    "Prefer the forward-only repair",
    "source environment, consistency boundary, migration head",
    "artifact/config revision, format/engine version, checksum, key availability",
    "retention through the rollback window",
    "recovery-point objective (RPO)",
    "recovery-time objective (RTO)",
    "last successful isolated restore drill",
    "A backup file or provider badge is not restore proof",
    "Inventory app-owned and provider-managed dependencies needed for "
    "application integrity",
    "state the estimated write-loss window",
    "obtain explicit owner acceptance of that loss/compensation plan",
    "restore into an isolated target first",
    "preview the exact source point, destination, scope, cutover, write-fence",
    "drain or park affected queues and jobs, record a final high-water mark",
    "verify affected writers reject new writes and fence stale writers",
    "fresh one-use scope-bound owner authorization",
    "sanitized write-ahead intent before the provider call",
    "reconcile before any retry",
    "Never substitute a generic `dump --clean`",
    "prove the live artifact/configuration and database migration head",
    "bounded production-safe read/write",
    "reconcile messages, webhooks, payments",
    "Do not infer statelessness from a DB-less stack",
    "browser-local or synchronized state, queues, object storage, caches, "
    "files, and third-party state",
    "store review, gradual rollout, and mixed installed versions",
)
ROLLBACK_INTEGRATION_REQUIREMENTS = {
    "agents": (
        "[rollback decision frame](docs/ROLLBACK.md)",
        "compatible with the current schema and configuration",
        "a database restore remains owner-gated",
    ),
    "claude": (
        "Choose the rollback lane; do not guess",
        "[docs/ROLLBACK.md](docs/ROLLBACK.md)",
        "neither lane retracts disclosure or downstream effects",
    ),
    "deploy": (
        '"Mechanically reversible" requires an exact immutable prior artifact',
        "evidence that it still works with the current schema, configuration, "
        "and external contracts",
        "Application rollback does not undo database writes, messages, webhooks, "
        "payments, permissions, credentials, or disclosure",
    ),
    "go-live": (
        "Recovery readiness proved",
        "current application/current schema, previous application/current schema",
        "current application/previous schema",
        "classify the application, database, and external-effect lanes",
    ),
    "migration": (
        "Read `docs/ROLLBACK.md` first",
        "Forward-only or additive migrations do not prove",
        "Production execution is owner-gated",
        "Preview the exact SQL, target, scope, write-fence, recovery point, and "
        "reconciliation path",
        "an absent history row is not proof that a failed migration made no "
        "changes",
    ),
}
ROLLBACK_UNSAFE_CLAIMS = (
    "rollback is instant",
    "rollback has zero data loss",
    "a snapshot makes restore reversible",
    "additive means backward-compatible",
    "the previous application is always compatible",
    "almost always use application rollback",
    "pause all workers",
)
ROLLBACK_CANONICAL_DISCLOSURE_MARKERS = (
    "github.com/",
    "source:",
)
ROLLBACK_DISCLOSURE_SENTINELS = (
    "source-project-identity.example",
    "provider-account-identifier.example",
    "competitive-implementation-detail.example",
)


def platform_precept_contract_errors(conventions: str, agents: str) -> list[str]:
    errors: list[str] = []
    for marker in (PLATFORM_PRECEPT_START, PLATFORM_PRECEPT_END):
        if conventions.count(marker) != 1:
            errors.append(f"marker:{marker}")
    if conventions.count(PLATFORM_PRECEPT_HEADING) != 1:
        errors.append("heading")
    if errors:
        return errors

    start_index = conventions.index(PLATFORM_PRECEPT_START)
    heading_index = conventions.index(PLATFORM_PRECEPT_HEADING)
    end_index = conventions.index(PLATFORM_PRECEPT_END)
    if not start_index < heading_index < end_index:
        return ["boundary-order"]
    section = conventions[
        start_index + len(PLATFORM_PRECEPT_START) : end_index
    ]
    normalized_section = " ".join(section.split())
    normalized_agents = " ".join(agents.split())
    for field in PLATFORM_HEADER_FIELDS:
        if section.count(field) != 1:
            errors.append(f"header:{field}")
    for requirement in PLATFORM_SECTION_REQUIREMENTS:
        if requirement not in normalized_section:
            errors.append(f"section:{requirement}")
    for requirement in PLATFORM_AGENT_REQUIREMENTS:
        if requirement not in normalized_agents:
            errors.append(f"agents:{requirement}")
    for disclosure in ("github.com/", "Source:"):
        if disclosure in section:
            errors.append(f"disclosure:{disclosure}")
    return errors


def irreversible_precept_contract_errors(
    agents: str, claude: str, deploy_policy: str
) -> list[str]:
    errors: list[str] = []
    for marker in (IRREVERSIBLE_PRECEPT_START, IRREVERSIBLE_PRECEPT_END):
        if agents.count(marker) != 1:
            errors.append(f"marker:{marker}")
    if agents.count(IRREVERSIBLE_PRECEPT_HEADING) != 1:
        errors.append("heading")
    if errors:
        return errors

    start_index = agents.index(IRREVERSIBLE_PRECEPT_START)
    heading_index = agents.index(IRREVERSIBLE_PRECEPT_HEADING)
    end_index = agents.index(IRREVERSIBLE_PRECEPT_END)
    if not start_index < heading_index < end_index:
        return ["boundary-order"]
    section = agents[
        start_index + len(IRREVERSIBLE_PRECEPT_START) : end_index
    ]
    normalized_section = " ".join(section.split())
    normalized_agents = " ".join(agents.split())
    normalized_claude = " ".join(claude.split())
    normalized_deploy = " ".join(deploy_policy.split())
    for requirement in IRREVERSIBLE_AGENT_REQUIREMENTS:
        if requirement not in normalized_section:
            errors.append(f"agents:{requirement}")
    for requirement in IRREVERSIBLE_AGENT_GLOBAL_REQUIREMENTS:
        if requirement not in normalized_agents:
            errors.append(f"agents-global:{requirement}")
    for requirement in IRREVERSIBLE_CLAUDE_REQUIREMENTS:
        if requirement not in normalized_claude:
            errors.append(f"claude:{requirement}")
    for requirement in IRREVERSIBLE_DEPLOY_REQUIREMENTS:
        if requirement not in normalized_deploy:
            errors.append(f"deploy:{requirement}")
    for forbidden in IRREVERSIBLE_AGENT_FORBIDDEN:
        if forbidden in normalized_agents:
            errors.append(f"agents-contradiction:{forbidden}")
    for forbidden in IRREVERSIBLE_CLAUDE_FORBIDDEN:
        if forbidden in normalized_claude:
            errors.append(f"claude-contradiction:{forbidden}")
    for forbidden in IRREVERSIBLE_DEPLOY_FORBIDDEN:
        if forbidden in normalized_deploy:
            errors.append(f"deploy-contradiction:{forbidden}")
    return errors


def rollback_contract_errors(
    rollback: str,
    agents: str,
    claude: str,
    deploy_policy: str,
    go_live: str,
    migration_rollback: str,
) -> list[str]:
    errors: list[str] = []
    for marker in (ROLLBACK_START, ROLLBACK_END):
        if rollback.count(marker) != 1:
            errors.append(f"marker:{marker}")
    if rollback.count(ROLLBACK_HEADING) != 1:
        errors.append("heading")
    if errors:
        return errors

    start_index = rollback.index(ROLLBACK_START)
    heading_index = rollback.index(ROLLBACK_HEADING)
    end_index = rollback.index(ROLLBACK_END)
    if not heading_index < start_index < end_index:
        return ["boundary-order"]
    section = rollback[start_index + len(ROLLBACK_START) : end_index]
    normalized_section = " ".join(section.split())
    for requirement in ROLLBACK_REQUIREMENTS:
        if requirement not in normalized_section:
            errors.append(f"rollback:{requirement}")

    integrations = {
        "agents": agents,
        "claude": claude,
        "deploy": deploy_policy,
        "go-live": go_live,
        "migration": migration_rollback,
    }
    for name, body in integrations.items():
        normalized_body = " ".join(body.split())
        for requirement in ROLLBACK_INTEGRATION_REQUIREMENTS[name]:
            if requirement not in normalized_body:
                errors.append(f"{name}:{requirement}")

    combined_lower = "\n".join((
        rollback,
        agents,
        claude,
        deploy_policy,
        go_live,
        migration_rollback,
    )).lower()
    for forbidden in ROLLBACK_UNSAFE_CLAIMS:
        if forbidden in combined_lower:
            errors.append(f"unsafe:{forbidden}")
    for disclosure in ROLLBACK_DISCLOSURE_SENTINELS:
        if disclosure in combined_lower:
            errors.append(f"disclosure:{disclosure}")
    for disclosure in ROLLBACK_CANONICAL_DISCLOSURE_MARKERS:
        if disclosure in rollback.lower():
            errors.append(f"rollback-disclosure:{disclosure}")
    return errors


def remove_contract_phrase(body: str, phrase: str) -> str:
    pattern = r"\s+".join(re.escape(part) for part in phrase.split())
    mutated, count = re.subn(pattern, "removed-contract-clause", body, count=1)
    if count != 1:
        raise AssertionError(f"mutation target missing: {phrase}")
    return mutated


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
    def assert_rollback_contract(output: Path, context: str) -> None:
        rollback_path = output / "docs" / "ROLLBACK.md"
        if not rollback_path.exists():
            raise AssertionError(f"{context}: generated docs/ROLLBACK.md is missing")
        rollback = rollback_path.read_text(encoding="utf-8")
        if "{{" in rollback:
            raise AssertionError(f"{context}: rollback frame contains a raw token")
        errors = rollback_contract_errors(
            rollback,
            (output / "AGENTS.md").read_text(encoding="utf-8"),
            (output / "CLAUDE.md").read_text(encoding="utf-8"),
            (output / "docs" / "DEPLOY_POLICY.md").read_text(encoding="utf-8"),
            (output / "docs" / "GO_LIVE.md").read_text(encoding="utf-8"),
            (output / "docs" / "migration-rollback.md").read_text(
                encoding="utf-8"
            ),
        )
        if errors:
            raise AssertionError(f"{context}: rollback contract errors: {errors}")

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
        DocIntegrityGeneratorTests.assert_rollback_contract(
            output, f"{answers.name} {settings}"
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
                    self.assert_rollback_contract(output, answers.name)
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

                    conventions = (
                        output / "docs" / "ENGINEERING_CONVENTIONS.md"
                    ).read_text(encoding="utf-8")
                    agents = (output / "AGENTS.md").read_text(encoding="utf-8")
                    claude = (output / "CLAUDE.md").read_text(encoding="utf-8")
                    deploy_policy = (
                        output / "docs" / "DEPLOY_POLICY.md"
                    ).read_text(encoding="utf-8")
                    contributing = (output / "CONTRIBUTING.md").read_text(
                        encoding="utf-8"
                    )
                    go_live = (output / "docs" / "GO_LIVE.md").read_text(
                        encoding="utf-8"
                    )
                    normalized_conventions = " ".join(conventions.split())
                    normalized_agents = " ".join(agents.split())
                    normalized_contributing = " ".join(contributing.split())
                    normalized_go_live = " ".join(go_live.split())
                    self.assertEqual(
                        conventions.count(
                            "## 8. Adopt canonical process code with a parity lock"
                        ),
                        1,
                        answers.name,
                    )
                    for required in (
                        "sanitized, synthetic fixture",
                        "compare their observable output byte-for-byte",
                        "Prove the assertion can fail with a deliberate mismatch",
                        "Vendor a pinned canonical copy first",
                        "change a single import/export seam",
                        "Keep rollback one seam wide",
                        "Separate **equivalence** from **improvement**",
                        "source-of-truth comparison table",
                        "digest manifest",
                    ):
                        self.assertIn(required, normalized_conventions, answers.name)
                    for forbidden in (
                        "production fixture",
                        "copy the secret",
                    ):
                        self.assertNotIn(forbidden, conventions, answers.name)
                    self.assertEqual(
                        platform_precept_contract_errors(conventions, agents),
                        [],
                        answers.name,
                    )
                    self.assertEqual(
                        irreversible_precept_contract_errors(
                            agents, claude, deploy_policy
                        ),
                        [],
                        answers.name,
                    )
                    self.assertEqual(
                        conventions.count(
                            "### CI integrity: unexecuted is not green"
                        ),
                        1,
                        answers.name,
                    )
                    self.assertEqual(
                        agents.count("**Unexecuted is not green**"),
                        1,
                        answers.name,
                    )
                    for required in (
                        "Only when hosted CI produced no substantive proof may "
                        "the local gate supply the quality signal",
                        "intended required proof for the exact candidate was "
                        "dispatched, executed, and "
                        "completed successfully",
                        "Check absent, disabled, or not dispatched | "
                        "Unexecuted—not green",
                        "Execution blocked by billing/quota state or runner "
                        "unavailability | Unexecuted or unavailable—not green",
                        "Queued or pending | Incomplete—not green",
                        "Failed, canceled, or timed out | Unsuccessful—not green",
                        "Explicitly optional check whose trigger does not apply | "
                        "Not applicable—not passed or green",
                        "Zero substantive proof steps executed | "
                        "Unexecuted—not green",
                        "local gate passed; hosted CI unexecuted",
                        "A local pass never overrides an executed hosted failure",
                        "never claims to satisfy or bypass the repository host's "
                        "merge policy",
                    ):
                        self.assertIn(
                            required, normalized_conventions, answers.name
                        )
                    for required in (
                        "authoritative quality evidence when hosted CI produced "
                        "no substantive proof",
                        "**Unexecuted is not green**",
                        "docs/ENGINEERING_CONVENTIONS.md#"
                        "ci-integrity-unexecuted-is-not-green",
                        "**unexecuted or unavailable—not passing**",
                        "local gate passed; hosted CI unexecuted",
                        "never overrides an executed hosted failure or bypasses "
                        "merge policy",
                    ):
                        self.assertIn(required, normalized_agents, answers.name)
                    for obsolete in (
                        "unavailable or flaky",
                        "*genuinely* failing",
                        "reasons unrelated to",
                    ):
                        self.assertNotIn(obsolete, conventions, answers.name)
                        self.assertNotIn(obsolete, agents, answers.name)
                    for required in (
                        "unavailable or unexecuted hosted check is not green",
                        "documented equivalent local gate may supply quality "
                        "evidence without claiming hosted success or bypassing "
                        "merge policy",
                    ):
                        self.assertIn(
                            required, normalized_contributing, answers.name
                        )
                    self.assertIn(
                        "Green locally is quality evidence",
                        normalized_go_live,
                        answers.name,
                    )
                    self.assertIn(
                        "not a claim that hosted CI executed or passed",
                        normalized_go_live,
                        answers.name,
                    )
                    for obsolete in (
                        "CI must be green",
                        "Obtain code review and green CI",
                    ):
                        self.assertNotIn(obsolete, agents, answers.name)
                    self.assertNotIn(
                        "CI must be green", contributing, answers.name
                    )
                    self.assertNotIn(
                        "Green locally ⇒ CI will be green",
                        go_live,
                        answers.name,
                    )

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

    def test_lift_process_requires_reversible_parity_evidence(self) -> None:
        lift_log = (ROOT / "docs" / "LIFT-LOG.md").read_text(encoding="utf-8")
        anatomy = (ROOT / "docs" / "ANATOMY.md").read_text(encoding="utf-8")
        normalized = " ".join(lift_log.split())

        for required in (
            "When a lift consolidates **executable process or infrastructure code**",
            "sanitized, synthetic fixture",
            "require byte-for-byte parity",
            "Vendor an immutable source commit or a resolved package artifact locked by digest/integrity metadata behind a thin local shim",
            "switch one import/export seam only after the parity test is green",
            "source-of-truth comparison table",
            "generalize and tokenize the lifted artifact **before** anything lands",
        ):
            self.assertIn(required, normalized)
        self.assertIn(
            "Nine reusable stack-neutral conventions",
            anatomy,
        )

    def test_platform_locked_precept_safety_clauses_are_mutation_proved(
        self,
    ) -> None:
        conventions = (
            ROOT / "template" / "docs" / "ENGINEERING_CONVENTIONS.md"
        ).read_text(encoding="utf-8")
        agents = (ROOT / "template" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(platform_precept_contract_errors(conventions, agents), [])

        convention_mutations = (
            PLATFORM_PRECEPT_START,
            PLATFORM_PRECEPT_END,
            *PLATFORM_HEADER_FIELDS,
            "synthetic/test inputs",
            "Run it on the exact candidate",
            "machine-observable required check for the exact candidate",
            "open the PR as a draft",
            "confirm the `auto-merge` label is absent",
            "Evidence composes per dimension",
            "never replaces or reclassifies",
            "grants no new native-toolchain exception",
        )
        for phrase in convention_mutations:
            with self.subTest(convention_phrase=phrase):
                mutated = remove_contract_phrase(conventions, phrase)
                self.assertNotEqual(
                    platform_precept_contract_errors(mutated, agents), []
                )

        swapped_markers = conventions.replace(
            PLATFORM_PRECEPT_START, "temporary-platform-boundary", 1
        ).replace(PLATFORM_PRECEPT_END, PLATFORM_PRECEPT_START, 1)
        swapped_markers = swapped_markers.replace(
            "temporary-platform-boundary", PLATFORM_PRECEPT_END, 1
        )
        self.assertNotEqual(
            platform_precept_contract_errors(swapped_markers, agents), []
        )

        heading_outside = conventions.replace(
            PLATFORM_PRECEPT_HEADING, "removed-platform-heading", 1
        )
        heading_outside = (
            f"{PLATFORM_PRECEPT_HEADING}\n" + heading_outside
        )
        self.assertNotEqual(
            platform_precept_contract_errors(heading_outside, agents), []
        )

        for phrase in (
            "same repository-owned portable target",
            "open the PR as a draft",
            "keep `auto-merge` absent",
            "until exact-candidate evidence is attached and reviewed",
        ):
            with self.subTest(agent_phrase=phrase):
                mutated = remove_contract_phrase(agents, phrase)
                self.assertNotEqual(
                    platform_precept_contract_errors(conventions, mutated), []
                )

    def test_irreversible_action_precept_is_mutation_proved(self) -> None:
        agents = (ROOT / "template" / "AGENTS.md").read_text(encoding="utf-8")
        claude = (ROOT / "template" / "CLAUDE.md").read_text(encoding="utf-8")
        deploy_policy = (
            ROOT / "template" / "docs" / "DEPLOY_POLICY.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            irreversible_precept_contract_errors(agents, claude, deploy_policy),
            [],
        )

        for phrase in (
            IRREVERSIBLE_PRECEPT_START,
            IRREVERSIBLE_PRECEPT_END,
            *IRREVERSIBLE_AGENT_REQUIREMENTS,
            *IRREVERSIBLE_AGENT_GLOBAL_REQUIREMENTS,
        ):
            with self.subTest(agent_phrase=phrase):
                mutated = remove_contract_phrase(agents, phrase)
                self.assertNotEqual(
                    irreversible_precept_contract_errors(
                        mutated, claude, deploy_policy
                    ),
                    [],
                )

        swapped_markers = agents.replace(
            IRREVERSIBLE_PRECEPT_START, "temporary-irreversible-boundary", 1
        ).replace(IRREVERSIBLE_PRECEPT_END, IRREVERSIBLE_PRECEPT_START, 1)
        swapped_markers = swapped_markers.replace(
            "temporary-irreversible-boundary", IRREVERSIBLE_PRECEPT_END, 1
        )
        self.assertNotEqual(
            irreversible_precept_contract_errors(
                swapped_markers, claude, deploy_policy
            ),
            [],
        )

        heading_outside = agents.replace(
            IRREVERSIBLE_PRECEPT_HEADING, "removed-irreversible-heading", 1
        )
        heading_outside = f"{IRREVERSIBLE_PRECEPT_HEADING}\n" + heading_outside
        self.assertNotEqual(
            irreversible_precept_contract_errors(
                heading_outside, claude, deploy_policy
            ),
            [],
        )

        trigger_mutations = {
            "or-becomes-and": agents.replace(
                "spends money or makes an external change",
                "spends money and makes an external change",
                1,
            ),
            "spend-trigger-removed": agents.replace("spends money or ", "", 1),
            "effect-trigger-removed": remove_contract_phrase(
                agents,
                "or makes an external change that cannot be reliably undone",
            ),
        }
        for name, trigger_mutation in trigger_mutations.items():
            with self.subTest(trigger_mutation=name):
                self.assertNotEqual(
                    irreversible_precept_contract_errors(
                        trigger_mutation, claude, deploy_policy
                    ),
                    [],
                )

        for phrase in IRREVERSIBLE_CLAUDE_REQUIREMENTS:
            with self.subTest(claude_phrase=phrase):
                mutated = remove_contract_phrase(claude, phrase)
                self.assertNotEqual(
                    irreversible_precept_contract_errors(
                        agents, mutated, deploy_policy
                    ),
                    [],
                )

        for phrase in IRREVERSIBLE_DEPLOY_REQUIREMENTS:
            with self.subTest(deploy_phrase=phrase):
                mutated = remove_contract_phrase(deploy_policy, phrase)
                self.assertNotEqual(
                    irreversible_precept_contract_errors(agents, claude, mutated),
                    [],
                )

        for forbidden in IRREVERSIBLE_AGENT_FORBIDDEN:
            with self.subTest(agent_contradiction=forbidden):
                self.assertNotEqual(
                    irreversible_precept_contract_errors(
                        f"{agents}\n{forbidden}\n", claude, deploy_policy
                    ),
                    [],
                )

        for forbidden in IRREVERSIBLE_CLAUDE_FORBIDDEN:
            with self.subTest(claude_contradiction=forbidden):
                self.assertNotEqual(
                    irreversible_precept_contract_errors(
                        agents, f"{claude}\n{forbidden}\n", deploy_policy
                    ),
                    [],
                )

        for forbidden in IRREVERSIBLE_DEPLOY_FORBIDDEN:
            with self.subTest(deploy_contradiction=forbidden):
                self.assertNotEqual(
                    irreversible_precept_contract_errors(
                        agents, claude, f"{deploy_policy}\n{forbidden}\n"
                    ),
                    [],
                )

    def test_rollback_decision_frame_is_mutation_proved(self) -> None:
        documents = {
            "rollback": (ROOT / "template" / "docs" / "ROLLBACK.md").read_text(
                encoding="utf-8"
            ),
            "agents": (ROOT / "template" / "AGENTS.md").read_text(
                encoding="utf-8"
            ),
            "claude": (ROOT / "template" / "CLAUDE.md").read_text(
                encoding="utf-8"
            ),
            "deploy": (
                ROOT / "template" / "docs" / "DEPLOY_POLICY.md"
            ).read_text(encoding="utf-8"),
            "go-live": (ROOT / "template" / "docs" / "GO_LIVE.md").read_text(
                encoding="utf-8"
            ),
            "migration": (
                ROOT / "template" / "docs" / "migration-rollback.md"
            ).read_text(encoding="utf-8"),
        }

        def errors(overrides: dict[str, str] | None = None) -> list[str]:
            candidate = {**documents, **(overrides or {})}
            return rollback_contract_errors(
                candidate["rollback"],
                candidate["agents"],
                candidate["claude"],
                candidate["deploy"],
                candidate["go-live"],
                candidate["migration"],
            )

        self.assertEqual(errors(), [])

        for phrase in (ROLLBACK_START, ROLLBACK_END, *ROLLBACK_REQUIREMENTS):
            with self.subTest(rollback_phrase=phrase):
                self.assertNotEqual(
                    errors({"rollback": remove_contract_phrase(
                        documents["rollback"], phrase
                    )}),
                    [],
                )

        swapped_markers = documents["rollback"].replace(
            ROLLBACK_START, "temporary-rollback-boundary", 1
        ).replace(ROLLBACK_END, ROLLBACK_START, 1)
        swapped_markers = swapped_markers.replace(
            "temporary-rollback-boundary", ROLLBACK_END, 1
        )
        self.assertNotEqual(errors({"rollback": swapped_markers}), [])

        heading_outside = documents["rollback"].replace(
            ROLLBACK_HEADING, "removed-rollback-heading", 1
        )
        heading_outside = f"{heading_outside}\n{ROLLBACK_HEADING}\n"
        self.assertNotEqual(errors({"rollback": heading_outside}), [])

        for name, requirements in ROLLBACK_INTEGRATION_REQUIREMENTS.items():
            for phrase in requirements:
                with self.subTest(integration=name, phrase=phrase):
                    self.assertNotEqual(
                        errors({name: remove_contract_phrase(
                            documents[name], phrase
                        )}),
                        [],
                    )

        for forbidden in (*ROLLBACK_UNSAFE_CLAIMS, *ROLLBACK_DISCLOSURE_SENTINELS):
            for name, body in documents.items():
                with self.subTest(document=name, unsafe_or_disclosure=forbidden):
                    self.assertNotEqual(
                        errors({name: f"{body}\n{forbidden}\n"}),
                        [],
                    )
        for disclosure in ROLLBACK_CANONICAL_DISCLOSURE_MARKERS:
            with self.subTest(canonical_disclosure=disclosure):
                self.assertNotEqual(
                    errors({
                        "rollback": f"{documents['rollback']}\n{disclosure}\n"
                    }),
                    [],
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
