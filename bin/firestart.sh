#!/usr/bin/env bash
#
# Project Firestarter — Dockerized entrypoint.
#
# Runs the generator inside a python:slim container so no Python is installed on
# the host (honours the "no host SDKs" rule the templates themselves enforce).
# The repo is mounted read-only; the parent directory is mounted read-write so
# the generator can write the stamped project next to this one.
#
# All arguments are forwarded to bin/generate.py, e.g.:
#   ./bin/firestart.sh                       # interactive
#   ./bin/firestart.sh --defaults
#   ./bin/firestart.sh --set project_slug=pilgrim --set stack=supabase-flutter
#   ./bin/firestart.sh --values answers.json --output ../project-pilgrim
#
# Escape hatch: FIRESTARTER_NATIVE=1 runs against a host Python 3 instead of
# Docker (handy in CI images that already have Python).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT_DIR="$(cd "${REPO_DIR}/.." && pwd)"

if [ "${FIRESTARTER_NATIVE:-0}" = "1" ]; then
    exec python3 "${REPO_DIR}/bin/generate.py" "$@"
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "✗ docker not found. Install Docker, or run with FIRESTARTER_NATIVE=1 (needs host python3)." >&2
    exit 1
fi

# -it only when attached to a TTY (so interactive prompts work; CI stays happy).
TTY_FLAGS=""
[ -t 0 ] && TTY_FLAGS="-it"

exec docker run --rm ${TTY_FLAGS} \
    -v "${PARENT_DIR}:/work" \
    -w "/work/$(basename "${REPO_DIR}")" \
    python:3.12-slim \
    python /work/"$(basename "${REPO_DIR}")"/bin/generate.py "$@"
