# Changelog

All notable changes to {{ project_name }} are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Pre-1.0: minor versions may include
breaking changes while the MVP stabilizes.

The canonical version lives in `/VERSION`; `make version-sync` propagates it into
the stack's package manifests (see `scripts/sync_version.sh`). To cut a release:
bump `VERSION`, run `make version-sync`, move `Unreleased` notes under a new
version heading, commit, and tag (`git tag -a vX.Y.Z`).

## [Unreleased]

## [0.1.0] - YYYY-MM-DD

_Set the date when you cut the first tagged release._

### Added
- Initial scaffold generated from
  [project-firestarter](https://github.com/pulkitsinghal/project-firestarter):
  Dockerized dev stack, CI (Tests · Lint & Typecheck · Build), AI-reviewed
  auto-merge, conventional-commit hooks, storyboard harness, and secret scanning.
