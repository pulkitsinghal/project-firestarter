#!/usr/bin/env python3
"""Fail-closed, secret-free verification of the orchestrator runtime policy."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tomllib
from pathlib import Path
from typing import Any


MAX_BYTES = 1_048_576
EXPECTED = {
    "model": "coordinator-model",
    "model_reasoning_effort": "high",
    "service_tier": "priority",
    "fast_mode": True,
    "multi_agent": True,
    "default_subagent_model": "coordinator-model",
    "default_subagent_reasoning_effort": "high",
}
RUNTIME_KEYS = {
    "model",
    "model_reasoning_effort",
    "service_tier",
    "fast_mode",
    "service_tier_attestation",
    "tier_provenance",
    "auth_mode",
}


class VerificationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code: str, message: str) -> None:
    raise VerificationError(code, message)


def regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        fail("INPUT_UNSAFE", f"{label} must be a regular non-symlink file")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
        fail("INPUT_UNSAFE", f"{label} must be a bounded regular file")
    return path


def load_toml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = tomllib.loads(regular_file(path, label).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        fail("CONFIG_INVALID", f"{label} is not valid UTF-8 TOML")
        raise AssertionError("unreachable") from exc
    if not isinstance(value, dict):
        fail("CONFIG_INVALID", f"{label} must contain a TOML table")
    return value


def no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("ATTESTATION_INVALID", "runtime attestation has duplicate keys")
        result[key] = value
    return result


def load_attestation(source: str) -> dict[str, Any]:
    if source == "-":
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    else:
        raw = regular_file(Path(source), "runtime attestation").read_bytes()
    if len(raw) > MAX_BYTES:
        fail("ATTESTATION_INVALID", "runtime attestation exceeds one megabyte")
    try:
        value = json.loads(raw, object_pairs_hook=no_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail("ATTESTATION_INVALID", "runtime attestation is not valid UTF-8 JSON")
        raise AssertionError("unreachable") from exc
    if not isinstance(value, dict) or set(value) != RUNTIME_KEYS:
        fail("ATTESTATION_INVALID", "runtime attestation has invalid fields")
    return value


def relevant_policy(config: dict[str, Any], code: str, label: str) -> dict[str, Any]:
    features = config.get("features")
    agents = config.get("agents")
    if not isinstance(features, dict) or not isinstance(agents, dict):
        fail(code, f"{label} features and agents tables are required")
    relevant = {
        "model": config.get("model"),
        "model_reasoning_effort": config.get("model_reasoning_effort"),
        "service_tier": config.get("service_tier"),
        "fast_mode": features.get("fast_mode"),
        "multi_agent": features.get("multi_agent"),
        "default_subagent_model": agents.get("default_subagent_model"),
        "default_subagent_reasoning_effort": agents.get(
            "default_subagent_reasoning_effort"
        ),
    }
    if relevant != EXPECTED:
        fail(code, f"{label} orchestrator runtime policy drifted")
    return relevant


def project_policy(config: dict[str, Any]) -> dict[str, Any]:
    return relevant_policy(config, "PROJECT_POLICY_DRIFT", "checked-in")


def user_runtime_policy(config: dict[str, Any]) -> dict[str, Any]:
    return relevant_policy(config, "USER_POLICY_DRIFT", "machine-local")


def project_is_trusted(config: dict[str, Any], project_root: Path) -> bool:
    projects = config.get("projects")
    if not isinstance(projects, dict):
        return False
    expected = str(project_root)
    for raw_path, value in projects.items():
        if not isinstance(raw_path, str) or not isinstance(value, dict):
            continue
        try:
            candidate = str(Path(raw_path).expanduser().resolve(strict=False))
        except (OSError, RuntimeError):
            continue
        if candidate == expected and value.get("trust_level") == "trusted":
            return True
    return False


def verify_runtime(value: dict[str, Any]) -> dict[str, Any]:
    source = value["service_tier_attestation"]
    if source not in {"runtime", "config-verified"}:
        fail(
            "SERVICE_TIER_UNATTESTED",
            "effective fast tier is neither runtime-attested nor config-verified",
        )
    expected_provenance = (
        "platform-runtime"
        if source == "runtime"
        else "trusted-project-and-user-config"
    )
    if value["tier_provenance"] != expected_provenance:
        fail(
            "SERVICE_TIER_PROVENANCE_INVALID",
            "service-tier provenance contradicts its verification source",
        )
    if value["auth_mode"] != "subscription":
        fail(
            "FAST_AUTH_MODE_UNSUPPORTED",
            "Subscription priority-tier semantics cannot be claimed for API-key auth",
        )
    expected_runtime = {
        "model": EXPECTED["model"],
        "model_reasoning_effort": EXPECTED["model_reasoning_effort"],
        "service_tier": EXPECTED["service_tier"],
        "fast_mode": EXPECTED["fast_mode"],
        "service_tier_attestation": source,
        "tier_provenance": expected_provenance,
        "auth_mode": "subscription",
    }
    if value != expected_runtime:
        fail("EFFECTIVE_RUNTIME_DRIFT", "effective root runtime does not match policy")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=os.getcwd())
    parser.add_argument(
        "--user-config",
        default=str(Path.home() / ".codex" / "config.toml"),
        help="User agent-CLI config used only to verify the project trust record.",
    )
    parser.add_argument(
        "--runtime-attestation",
        required=True,
        help="Bounded JSON file or '-' from a runtime surface that attests effective settings.",
    )
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        project_root = Path(arguments.project_root).resolve(strict=True)
        project_config = load_toml(
            project_root / ".codex" / "config.toml", "project config"
        )
        relevant = project_policy(project_config)
        user_config = load_toml(Path(arguments.user_config), "user config")
        if not project_is_trusted(user_config, project_root):
            fail(
                "PROJECT_UNTRUSTED",
                "project config is inactive until this exact project is trusted",
            )
        user_runtime_policy(user_config)
        runtime = verify_runtime(load_attestation(arguments.runtime_attestation))
        output = {
            "ok": True,
            "policy": {
                "root": {
                    "model": relevant["model"],
                    "reasoning_effort": relevant["model_reasoning_effort"],
                    "service_tier": relevant["service_tier"],
                    "fast_mode": relevant["fast_mode"],
                    "service_tier_attestation": runtime[
                        "service_tier_attestation"
                    ],
                },
                "worker_defaults": {
                    "model": relevant["default_subagent_model"],
                    "reasoning_effort": relevant[
                        "default_subagent_reasoning_effort"
                    ],
                    "service_tier": relevant["service_tier"],
                    "fast_mode": relevant["fast_mode"],
                },
                "multi_agent": relevant["multi_agent"],
                "root_excluded_from_worker_capacity": True,
            },
            "trust": "trusted",
            "precedence": {
                "project_policy_checked": True,
                "user_policy_checked": True,
                "service_tier_runtime_attested": (
                    runtime["service_tier_attestation"] == "runtime"
                ),
                "service_tier_config_verified": (
                    runtime["service_tier_attestation"] == "config-verified"
                ),
                "cli_or_profile_drift_denied": True,
            },
        }
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0
    except VerificationError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    except (OSError, RuntimeError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "INPUT_UNAVAILABLE",
                        "message": "required runtime policy input is unavailable",
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
