"""Contract: browser/storyboard evidence drives freshly built ship artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "bin" / "generate.py"
DECLARED_STACKS = tuple(
    json.loads((ROOT / "firestarter.config.json").read_text(encoding="utf-8"))["stack"]
)
ARTIFACT_STRATEGIES = {
    "fastapi-next": "production Next target",
    "supabase-flutter": "compiled Vite preview",
    "chrome-extension": "fresh extension/dist",
    "node-notifier": "production runtime image",
}


def service_block(compose: str, name: str) -> str:
    """Return one two-space-indented Compose service without parsing all YAML."""
    lines = compose.splitlines()
    marker = f"  {name}:"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise AssertionError(f"missing Compose service: {name}") from exc
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.fullmatch(r"  [A-Za-z0-9_.-]+:", lines[index]):
            end = index
            break
        if lines[index] and not lines[index].startswith(" "):
            end = index
            break
    return "\n".join(lines[start:end])


def top_level_block(text: str, name: str) -> str:
    lines = text.splitlines()
    marker = re.compile(rf"^{re.escape(name)}:(?:\s.*)?$")
    start = next((index for index, line in enumerate(lines) if marker.fullmatch(line)), None)
    if start is None:
        raise AssertionError(f"missing top-level block: {name}")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.fullmatch(r"[A-Za-z0-9_.-]+:", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def docker_stage(dockerfile: str, name: str) -> str:
    pattern = re.compile(rf"^FROM\s+.+\s+AS\s+{re.escape(name)}\s*$", re.MULTILINE)
    match = pattern.search(dockerfile)
    if not match:
        raise AssertionError(f"missing Docker stage: {name}")
    next_stage = re.search(r"^FROM\s+", dockerfile[match.end() :], re.MULTILINE)
    end = match.end() + next_stage.start() if next_stage else len(dockerfile)
    return dockerfile[match.start() : end]


class StoryboardArtifactFidelityContract(unittest.TestCase):
    maxDiff = None

    def assert_fastapi(self, stack: Path) -> None:
        compose = (stack / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (stack / "frontend" / "Dockerfile").read_text(encoding="utf-8")
        makefile = (stack / "Makefile").read_text(encoding="utf-8")

        development = service_block(compose, "frontend")
        production = service_block(compose, "frontend-storyboard")
        storyboard = service_block(compose, "storyboard")
        self.assertIn("target: development", development)
        self.assertIn('profiles: ["storyboard"]', production)
        self.assertIn("target: production", production)
        self.assertNotIn("ports:", production)
        self.assertNotIn("command:", production)
        self.assertNotIn("volumes:", production)
        self.assertIn("healthcheck:", production)
        self.assertIn("FRONTEND_URL: http://frontend-storyboard:3000", storyboard)
        self.assertIn("frontend-storyboard:", storyboard)
        self.assertIn("condition: service_healthy", storyboard)

        development_stage = docker_stage(dockerfile, "development")
        production_stage = docker_stage(dockerfile, "production")
        self.assertIn('CMD ["npm", "run", "dev"]', development_stage)
        self.assertIn("RUN npm run build", production_stage)
        self.assertIn('CMD ["npm", "run", "start"]', production_stage)
        self.assertNotIn("npm run dev", production_stage)
        self.assertNotIn('CMD ["npm", "run", "dev"]', production_stage)
        self.assertRegex(
            makefile,
            r"(?ms)^storyboard:.*\n\t.*up -d --build postgres redis backend"
            r".*\n\tcd backend && bash scripts/migrate\.sh"
            r".*\n\t.*build frontend-storyboard storyboard"
            r".*\n\t.*rm -sf frontend-storyboard"
            r".*\n\t.*run --rm storyboard",
        )

    def assert_supabase(self, stack: Path) -> None:
        compose = (stack / "docker-compose.yml").read_text(encoding="utf-8")
        makefile = (stack / "Makefile").read_text(encoding="utf-8")
        self.assertTrue((stack / "splash" / "package-lock.json").is_file())
        production = service_block(compose, "splash-storyboard")
        storyboard = service_block(compose, "storyboard")

        self.assertIn('profiles: ["storyboard"]', production)
        self.assertIn("npm ci --no-audit --no-fund", production)
        self.assertIn(
            "npm run build && npm run preview -- --host 0.0.0.0 --port 4173",
            production,
        )
        self.assertNotIn("npm run dev", production)
        self.assertIn("healthcheck:", production)
        self.assertIn("FRONTEND_URL: http://splash-storyboard:4173", storyboard)
        self.assertIn("splash-storyboard:", storyboard)
        self.assertIn("condition: service_healthy", storyboard)
        self.assertRegex(
            makefile,
            r"(?ms)^storyboard:.*\n\t.*build storyboard"
            r".*\n\t.*rm -sf splash-storyboard"
            r".*\n\t.*run --rm storyboard",
        )

    def assert_chrome(self, stack: Path) -> None:
        makefile = (stack / "Makefile").read_text(encoding="utf-8")
        compose = (stack / "docker-compose.yml").read_text(encoding="utf-8")
        storyboard_script = (stack / "storyboard" / "storyboard.mjs").read_text(
            encoding="utf-8"
        )
        e2e_fixture = (stack / "e2e" / "fixtures" / "extension.ts").read_text(
            encoding="utf-8"
        )
        e2e_config = (stack / "e2e" / "playwright.config.ts").read_text(
            encoding="utf-8"
        )
        storyboard_workflow = (
            stack / ".github" / "workflows" / "storyboard.yml"
        ).read_text(encoding="utf-8")
        e2e_workflow = (stack / ".github" / "workflows" / "e2e.yml").read_text(
            encoding="utf-8"
        )

        preparation = top_level_block(makefile, "browser-artifact-prepare")
        self.assertRegex(
            preparation,
            r"(?ms)^browser-artifact-prepare:.*\n"
            r"\t.*install.*\n\t.*clean.*\n\t.*build",
        )
        self.assertRegex(makefile, r"(?m)^storyboard: browser-artifact-prepare\b")
        self.assertRegex(makefile, r"(?m)^e2e-prepare: browser-artifact-prepare\b")
        self.assertIn("EXT_DIST=/work/extension/dist", service_block(compose, "storyboard"))
        self.assertIn("const sidebar = `${EXT_DIST}/sidebar.html`", storyboard_script)
        self.assertIn("if (!fs.existsSync(sidebar))", storyboard_script)
        self.assertIn("'extension', 'dist'", e2e_fixture)
        self.assertIn("node scripts/static-server.mjs", e2e_config)
        self.assertIn("Fixture-only server", e2e_config)
        self.assertNotIn("npm run dev", e2e_config)
        self.assertIn("run: make storyboard", storyboard_workflow)
        self.assertIn("run: make e2e-prepare", e2e_workflow)

    def assert_node_notifier(self, stack: Path) -> None:
        dockerfile = (stack / "Dockerfile").read_text(encoding="utf-8")
        compose = (stack / "docker-compose.yml").read_text(encoding="utf-8")
        makefile = (stack / "Makefile").read_text(encoding="utf-8")
        workflow = (stack / ".github" / "workflows" / "storyboard.yml").read_text(
            encoding="utf-8"
        )

        runtime = docker_stage(dockerfile, "runtime")
        app = top_level_block(compose, "x-app")
        storyboard = service_block(compose, "storyboard")
        self.assertIn("ENV NODE_ENV=production", runtime)
        self.assertIn('CMD ["node", "src/start-api.js"]', runtime)
        self.assertIn("target: runtime", app)
        self.assertIn("api:", storyboard)
        self.assertIn("condition: service_healthy", storyboard)
        self.assertIn("worker:", storyboard)
        self.assertNotIn("npm run dev", storyboard)
        self.assertRegex(makefile, r"(?m)^storyboard:.*\n(?:.*\n){0,3}\t.*up -d --build api worker redis")
        self.assertIn("run: make storyboard", workflow)
        self.assertNotIn("pg_isready", workflow)
        self.assertNotIn("backend/scripts/migrate.sh", workflow)
        self.assertIn('- "package.json"', workflow)
        self.assertIn('- "package-lock.json"', workflow)

    def assert_stack(self, root: Path, stack_name: str) -> None:
        strategy = {
            "fastapi-next": self.assert_fastapi,
            "supabase-flutter": self.assert_supabase,
            "chrome-extension": self.assert_chrome,
            "node-notifier": self.assert_node_notifier,
        }.get(stack_name)
        self.assertIsNotNone(strategy, f"declared stack lacks artifact strategy: {stack_name}")
        strategy(root)

    def test_every_declared_source_stack_has_an_explicit_strategy(self) -> None:
        self.assertEqual(set(DECLARED_STACKS), set(ARTIFACT_STRATEGIES))
        for stack_name in DECLARED_STACKS:
            with self.subTest(stack=stack_name):
                self.assert_stack(ROOT / "stacks" / stack_name, stack_name)

    def test_every_default_stamp_preserves_the_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp)
            for stack_name in DECLARED_STACKS:
                with self.subTest(stack=stack_name):
                    output = output_root / stack_name
                    subprocess.run(
                        [
                            sys.executable,
                            str(GENERATOR),
                            "--defaults",
                            "--set",
                            f"stack={stack_name}",
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
                    self.assert_stack(output, stack_name)

    def test_meta_contract_rejects_representative_regressions(self) -> None:
        fastapi = ROOT / "stacks" / "fastapi-next"
        compose = (fastapi / "docker-compose.yml").read_text(encoding="utf-8")
        mutated = compose.replace(
            "FRONTEND_URL: http://frontend-storyboard:3000",
            "FRONTEND_URL: http://frontend:3000",
            1,
        )
        with self.assertRaises(AssertionError):
            self.assertIn(
                "FRONTEND_URL: http://frontend-storyboard:3000",
                service_block(mutated, "storyboard"),
            )
        dockerfile = (fastapi / "frontend" / "Dockerfile").read_text(encoding="utf-8")
        mutated = dockerfile.replace(
            'CMD ["npm", "run", "start"]', 'CMD ["npm", "run", "dev"]', 1
        )
        with self.assertRaises(AssertionError):
            self.assertNotIn(
                'CMD ["npm", "run", "dev"]', docker_stage(mutated, "production")
            )
        makefile = (fastapi / "Makefile").read_text(encoding="utf-8")
        mutated = makefile.replace(
            "\n\t$(DC) --profile storyboard rm -sf frontend-storyboard", "", 1
        )
        with self.assertRaises(AssertionError):
            self.assertIn("rm -sf frontend-storyboard", mutated)
        mutated = compose.replace(
            '    profiles: ["storyboard"]',
            '    profiles: ["storyboard"]\n    command: ["npm", "run", "dev"]',
            1,
        )
        with self.assertRaises(AssertionError):
            self.assertNotIn("command:", service_block(mutated, "frontend-storyboard"))

        supabase = ROOT / "stacks" / "supabase-flutter"
        compose = (supabase / "docker-compose.yml").read_text(encoding="utf-8")
        mutated = compose.replace(
            "npm run build && npm run preview", "npm run build && npm run dev", 1
        )
        with self.assertRaises(AssertionError):
            self.assertIn(
                "npm run build && npm run preview -- --host 0.0.0.0 --port 4173",
                service_block(mutated, "splash-storyboard"),
            )
        mutated = compose.replace(
            "npm run build && npm run preview -- --host 0.0.0.0 --port 4173",
            "npm run build",
            1,
        )
        with self.assertRaises(AssertionError):
            self.assertIn("npm run preview", service_block(mutated, "splash-storyboard"))
        makefile = (supabase / "Makefile").read_text(encoding="utf-8")
        mutated = makefile.replace(
            "\n\t$(DC) --profile storyboard rm -sf splash-storyboard", "", 1
        )
        with self.assertRaises(AssertionError):
            self.assertIn("rm -sf splash-storyboard", mutated)

        node = ROOT / "stacks" / "node-notifier"
        compose = (node / "docker-compose.yml").read_text(encoding="utf-8")
        mutated = compose.replace("target: runtime", "target: test", 1)
        with self.assertRaises(AssertionError):
            self.assertIn("target: runtime", top_level_block(mutated, "x-app"))

        chrome = ROOT / "stacks" / "chrome-extension"
        fixture = (chrome / "e2e" / "fixtures" / "extension.ts").read_text(
            encoding="utf-8"
        )
        mutated = fixture.replace("'extension', 'dist'", "'extension', 'src'", 1)
        with self.assertRaises(AssertionError):
            self.assertIn("'extension', 'dist'", mutated)

        with self.assertRaisesRegex(AssertionError, "lacks artifact strategy"):
            self.assert_stack(ROOT / "stacks" / DECLARED_STACKS[0], "future-stack")

    def test_precept_and_ci_wiring_are_durable(self) -> None:
        conventions = (ROOT / "template" / "docs" / "ENGINEERING_CONVENTIONS.md").read_text(
            encoding="utf-8"
        )
        harness = (ROOT / "template" / "docs" / "storyboard-harness.md").read_text(
            encoding="utf-8"
        )
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        workflow = (
            ROOT / "template" / ".github" / "workflows" / "storyboard.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("unexecuted for artifact fidelity", conventions)
        self.assertIn("production-built", harness)
        self.assertIn("tests.test_storyboard_artifact_fidelity_contract", ci)
        self.assertIn("run: make storyboard", workflow)
        for watched in (
            '"docker-compose.yml"',
            '"Makefile"',
            '".github/workflows/storyboard.yml"',
        ):
            self.assertIn(watched, workflow)


if __name__ == "__main__":
    unittest.main()
