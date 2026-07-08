# CLAUDE.md

This is **project-firestarter**, a cookiecutter-style project template generator.

The full operating brief lives in **[AGENTS.md](AGENTS.md)** — read it. It covers
what this repo is, the two jobs (stamp a new project / lift a learning back), the
hard rules (no host SDKs, whitelist token safety, the CI job-name contract), and
the verify-before-commit steps.

Quick orientation:
- Generate: `./bin/firestart.sh` (runs in Docker — no host SDKs).
- Map of every file and its provenance: [docs/ANATOMY.md](docs/ANATOMY.md).
- `template/` and `stacks/` are **outputs** full of `{{ tokens }}`; they have
  their own `template/AGENTS.md` and `template/CLAUDE.md` for the *generated*
  project. This file governs the generator itself.
