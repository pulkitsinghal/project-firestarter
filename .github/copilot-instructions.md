# GitHub Copilot instructions

This repository is **project-firestarter**, a cookiecutter-style project template
generator. The authoritative agent brief is [`AGENTS.md`](../AGENTS.md) — follow it.

Key rules:
- The generator runs in Docker (`bin/firestart.sh`) — never install language SDKs
  on the host.
- Token substitution is whitelist-only (`firestarter.config.json`). Never touch
  GitHub Actions `${{ … }}` or JSX `style={{ … }}`.
- `template/` and `stacks/` are templated outputs containing `{{ tokens }}`.
