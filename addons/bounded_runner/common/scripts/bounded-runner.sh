#!/usr/bin/env bash
set -euo pipefail

IMAGE='python:3.13-bookworm@sha256:62eafe52c91cad83c2c74e630bfde917da8c253673e695665d454def84fc9a13'

usage() {
  echo "usage: $0 <preflight|run|aggregate|status> <project-relative-spec> [runner args]" >&2
  echo "optional: BOUNDED_RUNNER_DOCKER_ENV='NAME OTHER_NAME' passes named host vars" >&2
  exit 2
}

[[ $# -ge 2 ]] || usage
command_name=$1
spec_input=$2
shift 2
case "$command_name" in
  preflight|run|aggregate|status) ;;
  *) usage ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
project_root=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
marker=$project_root/.bounded-runner-root
[[ ! -L "$marker" && -f "$marker" ]] || {
  echo "bounded runner: canonical .bounded-runner-root marker is missing or unsafe" >&2
  exit 2
}
[[ $(<"$marker") == 'bounded-runner-root-v1' ]] || {
  echo "bounded runner: unsupported .bounded-runner-root marker" >&2
  exit 2
}

[[ ! -L "$spec_input" && -f "$spec_input" ]] || {
  echo "bounded runner: spec must be a regular, non-symlink file" >&2
  exit 2
}
spec_dir=$(CDPATH= cd -- "$(dirname -- "$spec_input")" && pwd -P)
spec_abs=$spec_dir/$(basename -- "$spec_input")
case "$spec_abs" in
  "$project_root"/*) spec_relative=${spec_abs#"$project_root"/} ;;
  *)
    echo "bounded runner: spec must stay inside the canonical project root" >&2
    exit 2
    ;;
esac

docker_args=(
  run --rm --init --pull missing
  --read-only --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777
  --cap-drop ALL --security-opt no-new-privileges
  --user "$(id -u):$(id -g)"
  --volume "$project_root:/workspace"
  --workdir /workspace
  --env PYTHONPATH=/workspace
  --env HOME=/tmp/runner-home
)

for name in ${BOUNDED_RUNNER_DOCKER_ENV:-}; do
  [[ $name =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "bounded runner: invalid name in BOUNDED_RUNNER_DOCKER_ENV" >&2
    exit 2
  }
  docker_args+=(--env "$name")
done

# Prevent Git Bash/MSYS from rewriting Linux container paths on Windows.
export MSYS_NO_PATHCONV=1
exec docker "${docker_args[@]}" "$IMAGE" \
  python3 -B -m tools.bounded_runner "$command_name" "/workspace/$spec_relative" "$@"
