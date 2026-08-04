#!/usr/bin/env python3
"""Transactional, local-only orchestrator control plane (Python stdlib only)."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import importlib.util
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import unicodedata
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit


INTERFACE_VERSION = "1.0"
SCHEMA_VERSION = "1.4"
POLICY_SCHEMA_VERSION = "1.0"
REQUIRED_ROOT_MODEL = "gpt-5.6-sol"
REQUIRED_ROOT_REASONING_EFFORT = "xhigh"
REQUIRED_SERVICE_TIER = "priority"
REQUIRED_FAST_MODE = True
FAST_PERFORMANCE_MULTIPLIER = 1.5
GPT56_STANDARD_CREDIT_MULTIPLIER = 2.5
EXIT_INVALID = 2
EXIT_CONFLICT = 3
EXIT_STATE = 4
MAX_JSON_BYTES = 1_048_576
MAX_TEXT = 50_000
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
PUBLIC_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,&()'’+-]{0,79}$")
PUBLIC_LABEL_SENSITIVE = re.compile(
    r"(?i)\b(?:password|passwd|secret|api[- ]?key|access[- ]?token|bearer)\b"
)
PUBLIC_LABEL_UUID = re.compile(
    r"(?:^|[^a-f0-9])[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-"
    r"[89ab][a-f0-9]{3}-[a-f0-9]{12}(?:$|[^a-f0-9])",
    re.IGNORECASE,
)
PUBLIC_OWNER_CLASSES = {"pm-proxy", "worker", "owner", "external"}
PUBLIC_LANE_CLASSES = {"running", "next", "waiting", "owner-gated", "complete"}
SELECTORS = {
    "owner",
    "org",
    "repo",
    "path",
    "environment",
    "data_class",
    "action",
    "task_kind",
}
PROVENANCE_KINDS = {
    "canonical",
    "owner-decision",
    "repo-policy",
    "team-policy",
    "environment-policy",
    "learned-preference",
}
GATES = {
    "NONE",
    "ACCOUNT_ACCESS",
    "AUTH_CHALLENGE",
    "BILLING_CHANGE_OR_SPEND",
    "DESTRUCTIVE_UNIQUE_DATA",
    "EXTERNAL_COMMUNICATION",
    "FORCE_HISTORY",
    "HARDWARE_MUTATION",
    "MATERIAL_SCOPE_CHANGE",
    "PRIVACY_CLINICAL_LEGAL_GOVERNED",
    "PRODUCTION_CHANGE",
    "PRODUCTION_DATA_MIGRATION",
    "PRODUCTION_DEPLOY",
    "PRODUCTION_RELEASE",
    "PROTECTION_BYPASS",
}
RULE_GATE_CODES = GATES | {"ANY_ENUMERATED"}
ACTION_TYPES = {
    "READ_INSPECT",
    "SAFE_RECONCILE",
    "ISOLATED_EDIT_TEST",
    "FOCUSED_BRANCH_COMMIT_PUSH_PR",
    "REVIEW_FIX",
    "NORMAL_MERGE",
    "EXACT_DEFAULT_RETEST",
    "TASK_OWNED_CLEANUP",
    "HOSTED_CI_BILLING_BLOCK",
    "BILLING_CHANGE_OR_SPEND",
    "ACCOUNT_OR_CREDENTIAL_CHANGE",
    "PRODUCTION_CHANGE",
    "EXTERNAL_COMMUNICATION",
    "DESTRUCTIVE_OR_FORCEFUL_CHANGE",
    "PRIVACY_OR_GOVERNED_DATA",
    "HARDWARE_MUTATION",
    "MATERIAL_SCOPE_CHANGE",
}
ACTION_GATE_MAP = {
    "ACCOUNT_OR_CREDENTIAL_CHANGE": {"ACCOUNT_ACCESS", "AUTH_CHALLENGE"},
    "BILLING_CHANGE_OR_SPEND": {"BILLING_CHANGE_OR_SPEND"},
    "PRODUCTION_CHANGE": {
        "PRODUCTION_CHANGE",
        "PRODUCTION_DATA_MIGRATION",
        "PRODUCTION_DEPLOY",
        "PRODUCTION_RELEASE",
    },
    "EXTERNAL_COMMUNICATION": {"EXTERNAL_COMMUNICATION"},
    "DESTRUCTIVE_OR_FORCEFUL_CHANGE": {
        "DESTRUCTIVE_UNIQUE_DATA",
        "FORCE_HISTORY",
        "PROTECTION_BYPASS",
    },
    "PRIVACY_OR_GOVERNED_DATA": {"PRIVACY_CLINICAL_LEGAL_GOVERNED"},
    "HARDWARE_MUTATION": {"HARDWARE_MUTATION"},
    "MATERIAL_SCOPE_CHANGE": {"MATERIAL_SCOPE_CHANGE"},
}
TASK_STATES = {
    "DRAFT",
    "PREFLIGHT",
    "RESERVED",
    "LAUNCH_PENDING",
    "RUNNING",
    "BLOCKED",
    "EXPIRED",
    "CLOSING",
    "CLOSED",
    "ARCHIVE_PENDING",
    "ARCHIVED",
    "DUPLICATE_STOP",
    "FAILED",
    "SUPERSEDED",
}
DURATION_BUCKETS = (
    "seconds",
    "5m",
    "10m",
    "15m",
    "20m",
    "30m",
    "45m",
    "60m+",
)
DURATION_LIMITS = {
    "seconds": 60,
    "5m": 450,
    "10m": 750,
    "15m": 1_050,
    "20m": 1_500,
    "30m": 2_250,
    "45m": 3_150,
    "60m+": 2_147_483_647,
}
NON_RUNTIME_STATES = {"blocked", "waiting"}
HEAVY_BUCKETS = {"45m", "60m+"}
SHORT_BUCKETS = {"seconds", "5m", "10m"}
MIN_CALIBRATION_SAMPLES = 5
MAX_CALIBRATION_SAMPLES = 20
HANDBACK_DEADLINE_CHECKS = 2
REMAINING_WORK_FRESH_SECONDS = 300
COMPLETION_SIGNALS = {
    "closure-signal",
    "objective-complete",
    "output-ready",
    "terminal-manifest",
    "tests-passed",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\b(?:password|secret|token)\s*[:=]\s*\S+"),
)


class ControlError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_status: int = EXIT_INVALID,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_status = exit_status
        self.details = details or {}


def fail(
    code: str,
    message: str,
    *,
    exit_status: int = EXIT_INVALID,
    details: dict[str, Any] | None = None,
) -> None:
    raise ControlError(code, message, exit_status=exit_status, details=details)


def strict(
    value: Any,
    required: set[str],
    optional: set[str] | None = None,
    label: str = "object",
) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("SCHEMA_INVALID", f"{label} must be an object")
    allowed = required | (optional or set())
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - allowed)
    if missing or unknown:
        fail(
            "SCHEMA_INVALID",
            f"{label} has invalid fields",
            details={"missing": missing, "unknown": unknown},
        )
    return value


def text(value: Any, label: str, maximum: int = MAX_TEXT, *, single_line: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        fail("SCHEMA_INVALID", f"{label} must be a non-empty bounded string")
    if "\x00" in value or "\x1b" in value:
        fail("SCHEMA_INVALID", f"{label} contains a forbidden control character")
    if single_line and any(
        character in "\r\n" or unicodedata.category(character).startswith("C")
        for character in value
    ):
        fail("SCHEMA_INVALID", f"{label} must be a single control-free line")
    return value


def identifier(value: Any, label: str) -> str:
    result = text(value, label, 128, single_line=True)
    if not ID_RE.fullmatch(result):
        fail("SCHEMA_INVALID", f"{label} is not a stable identifier")
    return result


def timestamp(value: Any, label: str = "now") -> str:
    result = text(value, label, 40, single_line=True)
    if not TIME_RE.fullmatch(result):
        fail("SCHEMA_INVALID", f"{label} must be an RFC3339 UTC timestamp")
    return result


def bounded_int(value: Any, label: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        fail("SCHEMA_INVALID", f"{label} must be an integer from {low} to {high}")
    return value


def boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        fail("SCHEMA_INVALID", f"{label} must be a boolean")
    return value


def enum(value: Any, label: str, allowed: set[str]) -> str:
    result = text(value, label, 128, single_line=True)
    if result not in allowed:
        fail("SCHEMA_INVALID", f"{label} is not an allowed value")
    return result


def reject_sensitive(value: Any, label: str = "value") -> None:
    if isinstance(value, str):
        if len(value) > MAX_TEXT:
            fail("PRIVACY_REJECTED", f"{label} is too large")
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                fail("PRIVACY_REJECTED", f"{label} contains a secret-like value")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_sensitive(item, f"{label}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_sensitive(item, f"{label}.{key}")


def pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            fail("JSON_DUPLICATE_KEY", "JSON contains a duplicate object key")
        output[key] = value
    return output


def read_json(source: str) -> Any:
    if source == "-":
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
    else:
        path = Path(source)
        if path.is_symlink() or not path.is_file():
            fail("INPUT_UNSAFE", "input must be a regular non-symlink file")
        if path.stat().st_size > MAX_JSON_BYTES:
            fail("INPUT_TOO_LARGE", "input exceeds one megabyte")
        raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        fail("INPUT_TOO_LARGE", "input exceeds one megabyte")
    try:
        return json.loads(raw, object_pairs_hook=pairs_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("JSON_INVALID", "input must be valid UTF-8 JSON")
    raise AssertionError("unreachable")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256((canonical(value) + "\n").encode()).hexdigest()


def coarse_label(value: Any, label: str) -> str:
    result = identifier(value, label)
    if (
        "/" in result
        or "\\" in result
        or ".." in result
        or "@" in result
        or ":" in result
    ):
        fail(
            "PRIVACY_REJECTED",
            f"{label} must be a coarse non-path, non-identity label",
        )
    return result


def validate_public_metadata(value: Any) -> dict[str, str]:
    metadata = strict(
        value,
        {"publicLabel", "ownerClass", "laneClass"},
        label="public_metadata",
    )
    public_label = text(
        metadata["publicLabel"], "public_metadata.publicLabel", 80, single_line=True
    )
    if (
        not PUBLIC_LABEL_RE.fullmatch(public_label)
        or ".." in public_label
        or PUBLIC_LABEL_SENSITIVE.search(public_label)
        or PUBLIC_LABEL_UUID.search(public_label)
    ):
        fail(
            "PRIVACY_REJECTED",
            "public_metadata.publicLabel must be a bounded sanitized label",
        )
    if metadata["ownerClass"] not in PUBLIC_OWNER_CLASSES:
        fail("PRIVACY_REJECTED", "public_metadata.ownerClass is not allowlisted")
    if metadata["laneClass"] not in PUBLIC_LANE_CLASSES:
        fail("PRIVACY_REJECTED", "public_metadata.laneClass is not allowlisted")
    return {
        "publicLabel": public_label,
        "ownerClass": metadata["ownerClass"],
        "laneClass": metadata["laneClass"],
    }


def optional_seconds(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return bounded_int(value, label, 0, 2_147_483_647)


def bucket_for_seconds(seconds: int) -> str:
    for bucket in DURATION_BUCKETS:
        if seconds < DURATION_LIMITS[bucket]:
            return bucket
    return "60m+"


def utc_instant(raw: str) -> datetime:
    return datetime.fromisoformat(raw.removesuffix("Z") + "+00:00")


def duration_index(bucket: str) -> int:
    try:
        return DURATION_BUCKETS.index(bucket)
    except ValueError:
        fail("SCHEMA_INVALID", "duration bucket is invalid")
    raise AssertionError("unreachable")


def validate_duration_estimate(
    value: Any,
    *,
    task_family_fallback: str,
    environment_fallback: str,
) -> dict[str, Any]:
    if value is None:
        return {
            "estimate_version": 1,
            "estimated_bucket": "60m+",
            "confidence": "low",
            "task_family": coarse_label(
                task_family_fallback, "duration.task_family"
            ),
            "tool_family": "unspecified",
            "environment_class": coarse_label(
                environment_fallback, "duration.environment_class"
            ),
            "evidence_basis": ["compatibility-fallback"],
            "expected_components": {
                "setup_seconds": None,
                "test_seconds": None,
                "remote_wait_seconds": None,
            },
            "heavyweight_concurrency_cap": 64,
        }
    estimate = strict(
        value,
        {
            "estimate_version",
            "estimated_bucket",
            "confidence",
            "task_family",
            "tool_family",
            "environment_class",
            "evidence_basis",
            "expected_components",
            "heavyweight_concurrency_cap",
        },
        label="duration estimate",
    )
    if estimate["estimated_bucket"] not in DURATION_BUCKETS:
        fail("SCHEMA_INVALID", "duration.estimated_bucket is invalid")
    if estimate["confidence"] not in {"low", "moderate", "high"}:
        fail("SCHEMA_INVALID", "duration.confidence is invalid")
    basis = estimate["evidence_basis"]
    if not isinstance(basis, list) or not 1 <= len(basis) <= 20:
        fail(
            "SCHEMA_INVALID",
            "duration.evidence_basis must be a non-empty bounded list",
        )
    safe_basis = [
        coarse_label(item, "duration.evidence_basis[]") for item in basis
    ]
    components = strict(
        estimate["expected_components"],
        {"setup_seconds", "test_seconds", "remote_wait_seconds"},
        label="duration.expected_components",
    )
    result = {
        "estimate_version": bounded_int(
            estimate["estimate_version"], "duration.estimate_version", 1, 1_000_000
        ),
        "estimated_bucket": estimate["estimated_bucket"],
        "confidence": estimate["confidence"],
        "task_family": coarse_label(
            estimate["task_family"], "duration.task_family"
        ),
        "tool_family": coarse_label(
            estimate["tool_family"], "duration.tool_family"
        ),
        "environment_class": coarse_label(
            estimate["environment_class"], "duration.environment_class"
        ),
        "evidence_basis": safe_basis,
        "expected_components": {
            "setup_seconds": optional_seconds(
                components["setup_seconds"],
                "duration.expected_components.setup_seconds",
            ),
            "test_seconds": optional_seconds(
                components["test_seconds"],
                "duration.expected_components.test_seconds",
            ),
            "remote_wait_seconds": optional_seconds(
                components["remote_wait_seconds"],
                "duration.expected_components.remote_wait_seconds",
            ),
        },
        "heavyweight_concurrency_cap": bounded_int(
            estimate["heavyweight_concurrency_cap"],
            "duration.heavyweight_concurrency_cap",
            1,
            64,
        ),
    }
    reject_sensitive(result, "duration estimate")
    return result


def trusted_system_path_alias(path: Path) -> bool:
    return (
        sys.platform == "darwin"
        and str(path) in {"/tmp", "/var"}
        and path.resolve() == Path(f"/private{path}").resolve()
        and path.lstat().st_uid == 0
    )


def safe_state_dir(raw: str) -> Path:
    path = Path(raw).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            if trusted_system_path_alias(current):
                continue
            fail(
                "STATE_UNSAFE",
                "state directory path cannot contain a symlink",
                exit_status=EXIT_STATE,
            )
    if path.exists() and path.is_symlink():
        fail("STATE_UNSAFE", "state directory cannot be a symlink", exit_status=EXIT_STATE)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    if hasattr(os, "getuid") and path.stat().st_uid != os.getuid():
        fail("STATE_OWNERSHIP", "state directory must be owned by the current user", exit_status=EXIT_STATE)
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        fail("STATE_PERMISSIONS", "state directory must have mode 0700", exit_status=EXIT_STATE)
    return path.resolve()


def no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            if trusted_system_path_alias(current):
                continue
            fail("SYMLINK_ESCAPE", "repository target contains a symlink")


def normalize_remote(value: Any) -> str:
    raw = text(value, "target.remote", 500, single_line=True)
    if raw.startswith("git@") and ":" in raw:
        host, remainder = raw[4:].split(":", 1)
        path = remainder
    else:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
            fail("SCHEMA_INVALID", "target.remote must use https or ssh")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            fail("PRIVACY_REJECTED", "target.remote cannot include credentials or query data")
        host = parsed.hostname
        path = parsed.path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        fail("SCHEMA_INVALID", "target.remote must identify host/org/repository")
    return f"{host.lower()}/{parts[0]}/{parts[1]}"


def safe_http_url(value: Any, label: str) -> str:
    raw = text(value, label, 2000, single_line=True)
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        fail("SCHEMA_INVALID", f"{label} must be a credential-free HTTP(S) URL")
    return raw


def normalize_relative_path(value: Any) -> str:
    raw = text(value, "target.path", 1000, single_line=True)
    if not raw.startswith("/") or "\x00" in raw:
        fail("SCHEMA_INVALID", "target.path must be repository-absolute")
    parts = PurePosixPath(raw).parts
    if ".." in parts:
        fail("PATH_ESCAPE", "target.path cannot traverse upward")
    return "/" + "/".join(part for part in parts if part != "/")


def verified_repository_remote(root: Path) -> str:
    marker = root / ".git"
    if marker.is_symlink() or not marker.exists():
        fail("REPOSITORY_IDENTITY_INVALID", "target.repo_root is not a Git root")
    if marker.is_dir():
        git_dir = marker.resolve(strict=True)
    elif marker.is_file():
        content = marker.read_text(encoding="utf-8")
        if len(content) > 4096 or not content.startswith("gitdir: "):
            fail("REPOSITORY_IDENTITY_INVALID", "worktree Git marker is invalid")
        candidate = Path(content[8:].strip())
        if not candidate.is_absolute():
            candidate = root / candidate
        no_symlink_components(candidate)
        git_dir = candidate.resolve(strict=True)
    else:
        fail("REPOSITORY_IDENTITY_INVALID", "target.repo_root Git marker is invalid")
    common_dir = git_dir
    common_marker = git_dir / "commondir"
    if common_marker.is_file() and not common_marker.is_symlink():
        raw_common = common_marker.read_text(encoding="utf-8")
        if len(raw_common) > 4096:
            fail("REPOSITORY_IDENTITY_INVALID", "worktree common Git directory is invalid")
        common_candidate = Path(raw_common.strip())
        if not common_candidate.is_absolute():
            common_candidate = git_dir / common_candidate
        no_symlink_components(common_candidate)
        common_dir = common_candidate.resolve(strict=True)
    config_path = common_dir / "config"
    if (
        config_path.is_symlink()
        or not config_path.is_file()
        or config_path.stat().st_size > MAX_JSON_BYTES
    ):
        fail("REPOSITORY_IDENTITY_INVALID", "Git origin configuration is unavailable")
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(config_path.read_text(encoding="utf-8"))
        origin = parser.get('remote "origin"', "url")
    except (configparser.Error, KeyError, UnicodeDecodeError):
        fail("REPOSITORY_IDENTITY_INVALID", "Git origin configuration is invalid")
    return normalize_remote(origin)


def normalize_target(value: Any) -> dict[str, str]:
    target = strict(
        value,
        {"remote", "repo_root", "path", "base_sha", "resource_mode"},
        label="target",
    )
    remote = normalize_remote(target["remote"])
    root = Path(text(target["repo_root"], "target.repo_root", 4000, single_line=True))
    if not root.is_absolute() or not root.is_dir():
        fail("SCHEMA_INVALID", "target.repo_root must be an existing absolute directory")
    no_symlink_components(root)
    resolved_root = root.resolve(strict=True)
    if verified_repository_remote(resolved_root) != remote:
        fail(
            "REPOSITORY_IDENTITY_MISMATCH",
            "target.remote does not match the verified repository origin",
        )
    relative = normalize_relative_path(target["path"])
    candidate = resolved_root.joinpath(relative.lstrip("/"))
    no_symlink_components(candidate)
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        fail("PATH_ESCAPE", "target.path escapes the repository root")
    base_sha = text(target["base_sha"], "target.base_sha", 40, single_line=True).lower()
    if not SHA_RE.fullmatch(base_sha):
        fail("SCHEMA_INVALID", "target.base_sha must be a full lowercase SHA")
    if target["resource_mode"] not in {"repo-wide", "path"}:
        fail("SCHEMA_INVALID", "target.resource_mode is invalid")
    return {
        "remote": remote,
        "repo_root": str(resolved_root),
        "path": relative,
        "base_sha": base_sha,
        "resource_mode": target["resource_mode"],
        "canonical_key": (
            f"{remote}|{os.path.normcase(str(resolved_root)).casefold()}|"
            f"{os.path.normcase(relative).casefold()}"
        ),
    }


def targets_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["remote"] != right["remote"] or left["repo_root"] != right["repo_root"]:
        return False
    if left["resource_mode"] == "repo-wide" or right["resource_mode"] == "repo-wide":
        return True
    left_parts = PurePosixPath(left["path"].casefold()).parts
    right_parts = PurePosixPath(right["path"].casefold()).parts
    width = min(len(left_parts), len(right_parts))
    return left_parts[:width] == right_parts[:width]


def validate_context(value: Any, required_action: str) -> dict[str, str]:
    context = strict(value, SELECTORS, label="context")
    output = {key: text(context[key], f"context.{key}", 1000, single_line=True) for key in SELECTORS}
    if output["action"] != required_action:
        fail("SCHEMA_INVALID", f"context.action must be {required_action}")
    reject_sensitive(output, "context")
    return output


def load_root_role_guard() -> Any:
    """Load the sibling guard without relying on the process import path."""

    guard_path = Path(__file__).resolve().with_name("root_role_guard.py")
    try:
        spec = importlib.util.spec_from_file_location(
            "firestarter_root_role_guard", guard_path
        )
        if spec is None or spec.loader is None:
            raise ImportError("guard module has no loader")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        fail(
            "ROOT_GUARD_UNAVAILABLE",
            "root-role guard is unavailable; proposed action denied",
            exit_status=EXIT_STATE,
        )


def validate_rule(value: Any) -> dict[str, Any]:
    rule = strict(
        value,
        {
            "schema_version",
            "id",
            "rule_revision",
            "state",
            "scope",
            "precedence_tier",
            "priority",
            "effect",
            "directive",
            "gate_code",
            "provenance",
            "effective_at",
            "expires_at",
            "supersedes",
            "conflict_group",
            "privacy",
        },
        label="policy rule",
    )
    if rule["schema_version"] != POLICY_SCHEMA_VERSION:
        fail("VERSION_UNSUPPORTED", "policy rule schema version is unsupported")
    rule_id = text(rule["id"], "rule.id", 80, single_line=True)
    if not RULE_ID_RE.fullmatch(rule_id):
        fail("SCHEMA_INVALID", "rule.id is invalid")
    scope = rule["scope"]
    if not isinstance(scope, dict) or not scope or not set(scope) <= SELECTORS:
        fail("SCHEMA_INVALID", "rule.scope is invalid")
    normalized_scope = {
        key: text(selector, f"rule.scope.{key}", 1000, single_line=True)
        for key, selector in scope.items()
    }
    if rule["state"] not in {"active", "superseded", "expired", "revoked", "quarantined"}:
        fail("SCHEMA_INVALID", "rule.state is invalid")
    if rule["effect"] not in {
        "allow_pm_proxy",
        "require_owner",
        "deny",
        "constraint",
        "annotate",
    }:
        fail("SCHEMA_INVALID", "rule.effect is invalid")
    directive = strict(rule["directive"], {"code", "summary"}, {"args"}, "rule.directive")
    normalized_directive = {
        "code": identifier(directive["code"], "rule.directive.code"),
        "summary": text(directive["summary"], "rule.directive.summary", 2000),
        "args": directive.get("args", {}),
    }
    if normalized_directive["args"] != {}:
        fail(
            "SCHEMA_INVALID",
            "rule.directive.args is reserved and must be empty in interface 1.0",
        )
    gate = rule["gate_code"]
    if gate is not None and gate not in RULE_GATE_CODES - {"NONE"}:
        fail("SCHEMA_INVALID", "rule.gate_code is invalid")
    if rule["effect"] == "require_owner" and gate is None:
        fail("SCHEMA_INVALID", "require_owner rule needs gate_code")
    provenance = strict(
        rule["provenance"],
        {
            "source_kind",
            "source_thread_id",
            "source_turn_id",
            "recorded_at",
            "redacted_summary",
        },
        label="rule.provenance",
    )
    normalized_provenance = {
        "source_kind": text(provenance["source_kind"], "source_kind", 50, single_line=True),
        "source_thread_id": provenance["source_thread_id"],
        "source_turn_id": provenance["source_turn_id"],
        "recorded_at": timestamp(provenance["recorded_at"], "recorded_at"),
        "redacted_summary": text(
            provenance["redacted_summary"], "redacted_summary", 1000, single_line=True
        ),
    }
    if normalized_provenance["source_kind"] not in PROVENANCE_KINDS:
        fail("SCHEMA_INVALID", "rule.provenance.source_kind is invalid")
    for optional_id in ("source_thread_id", "source_turn_id"):
        if normalized_provenance[optional_id] is not None:
            normalized_provenance[optional_id] = identifier(
                normalized_provenance[optional_id], optional_id
            )
    if not isinstance(rule["supersedes"], list) or any(
        not isinstance(item, str) or not RULE_ID_RE.fullmatch(item)
        for item in rule["supersedes"]
    ):
        fail("SCHEMA_INVALID", "rule.supersedes is invalid")
    expires = None if rule["expires_at"] is None else timestamp(rule["expires_at"], "expires_at")
    conflict_group = rule["conflict_group"]
    if conflict_group is not None:
        conflict_group = identifier(conflict_group, "conflict_group")
    output = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "id": rule_id,
        "rule_revision": bounded_int(rule["rule_revision"], "rule_revision", 1, 1_000_000),
        "state": rule["state"],
        "scope": normalized_scope,
        "precedence_tier": bounded_int(rule["precedence_tier"], "precedence_tier", 1, 6),
        "priority": bounded_int(rule["priority"], "priority", 0, 1000),
        "effect": rule["effect"],
        "directive": normalized_directive,
        "gate_code": gate,
        "provenance": normalized_provenance,
        "effective_at": timestamp(rule["effective_at"], "effective_at"),
        "expires_at": expires,
        "supersedes": rule["supersedes"],
        "conflict_group": conflict_group,
        "privacy": rule["privacy"],
    }
    if output["privacy"] not in {"public-policy", "local-redacted"}:
        fail("SCHEMA_INVALID", "rule.privacy is invalid")
    reject_sensitive(output, f"rule.{rule_id}")
    return output


def validate_policy(value: Any) -> dict[str, Any]:
    ledger = strict(value, {"schema_version", "ledger_version", "rules"}, label="policy ledger")
    if ledger["schema_version"] != POLICY_SCHEMA_VERSION:
        fail("VERSION_UNSUPPORTED", "policy ledger schema version is unsupported")
    rules = [validate_rule(item) for item in ledger["rules"]] if isinstance(ledger["rules"], list) else []
    if not rules:
        fail("SCHEMA_INVALID", "policy ledger requires rules")
    ids = [(rule["id"], rule["rule_revision"]) for rule in rules]
    if len(ids) != len(set(ids)):
        fail("SCHEMA_INVALID", "policy rule identity/revision must be unique")
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "ledger_version": bounded_int(ledger["ledger_version"], "ledger_version", 1, 1_000_000),
        "rules": rules,
    }


def selector_match(selector: str, actual: str, key: str) -> bool:
    if selector == "*":
        return True
    if key == "path" and selector.endswith("/**"):
        prefix = selector[:-3].rstrip("/") or "/"
        return actual == prefix or actual.startswith(prefix.rstrip("/") + "/")
    return selector == actual


def resolve_rules(
    rules: list[dict[str, Any]], context: dict[str, str], now: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    excluded: list[dict[str, str]] = []
    candidates: list[dict[str, Any]] = []
    for rule in rules:
        reason = None
        if rule["state"] != "active":
            reason = f"STATE_{rule['state'].upper()}"
        elif rule["effective_at"] > now:
            reason = "NOT_YET_EFFECTIVE"
        elif rule["expires_at"] is not None and rule["expires_at"] <= now:
            reason = "EXPIRED"
        elif not all(
            selector_match(selector, context[key], key)
            for key, selector in rule["scope"].items()
        ):
            reason = "SCOPE_MISMATCH"
        if reason:
            excluded.append({"rule_id": rule["id"], "reason_code": reason})
        else:
            candidates.append(rule)
    superseded = {item for rule in candidates for item in rule["supersedes"]}
    active = []
    for rule in candidates:
        if rule["id"] in superseded:
            excluded.append({"rule_id": rule["id"], "reason_code": "SUPERSEDED"})
        else:
            active.append(rule)
    active.sort(key=lambda rule: rule["id"])
    active.sort(key=lambda rule: rule["effective_at"], reverse=True)
    active.sort(key=lambda rule: rule["priority"], reverse=True)
    active.sort(
        key=lambda rule: sum(value != "*" for value in rule["scope"].values()),
        reverse=True,
    )
    active.sort(key=lambda rule: rule["precedence_tier"])
    groups: dict[str, list[dict[str, Any]]] = {}
    for rule in active:
        if rule["conflict_group"]:
            groups.setdefault(rule["conflict_group"], []).append(rule)
    overridden: set[tuple[str, int]] = set()
    for group in groups.values():
        best = group[0]
        best_rank = (
            best["precedence_tier"],
            sum(value != "*" for value in best["scope"].values()),
            best["priority"],
            best["effective_at"],
        )
        peers = [
            rule
            for rule in group
            if (
                rule["precedence_tier"],
                sum(value != "*" for value in rule["scope"].values()),
                rule["priority"],
                rule["effective_at"],
            )
            == best_rank
        ]
        if len({(rule["effect"], rule["gate_code"]) for rule in peers}) > 1:
            fail(
                "POLICY_CONFLICT",
                "equal-precedence policy effects conflict",
                exit_status=EXIT_CONFLICT,
                details={"rule_ids": sorted(rule["id"] for rule in peers)},
            )
        for rule in group:
            if rule not in peers:
                overridden.add((rule["id"], rule["rule_revision"]))
                excluded.append(
                    {
                        "rule_id": rule["id"],
                        "reason_code": "OVERRIDDEN_BY_HIGHER_PRECEDENCE",
                    }
                )
    active = [
        rule
        for rule in active
        if (rule["id"], rule["rule_revision"]) not in overridden
    ]
    included = []
    for rule in active:
        copy = dict(rule)
        copy["why"] = {
            "reason_code": "MATCHED",
            "precedence_tier": rule["precedence_tier"],
            "specificity": sum(value != "*" for value in rule["scope"].values()),
            "priority": rule["priority"],
            "provenance": rule["provenance"],
        }
        included.append(copy)
    excluded.sort(key=lambda item: (item["rule_id"], item["reason_code"]))
    return included, excluded


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_rules (
  rule_id TEXT NOT NULL,
  rule_revision INTEGER NOT NULL,
  body_json TEXT NOT NULL,
  PRIMARY KEY (rule_id, rule_revision)
);
CREATE TABLE IF NOT EXISTS policy_updates (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  rule_revision INTEGER NOT NULL,
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  source_event_key TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  outcome_key TEXT NOT NULL UNIQUE,
  external_thread_id TEXT,
  state TEXT NOT NULL,
  priority INTEGER NOT NULL,
  dependencies_json TEXT NOT NULL,
  target_json TEXT NOT NULL,
  prompt_reference TEXT NOT NULL,
  policy_revision INTEGER NOT NULL,
  applicable_rule_ids_json TEXT NOT NULL,
  lease_epoch INTEGER NOT NULL,
  fencing_token INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  block_json TEXT,
  closure_json TEXT,
  source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS owner_claims (
  claim_id TEXT PRIMARY KEY,
  canonical_resource_key TEXT NOT NULL,
  target_json TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  lease_epoch INTEGER NOT NULL,
  fencing_token INTEGER NOT NULL,
  status TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  heartbeat_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
  outbox_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  payload_json TEXT NOT NULL,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS launches (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  envelope_json TEXT NOT NULL,
  receipt_json TEXT,
  issued_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  route TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  rule_ids_json TEXT NOT NULL,
  explanation TEXT NOT NULL,
  gate_fingerprint TEXT,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handbacks (
  handback_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  body_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capacity_sagas (
  saga_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
  configured_capacity INTEGER NOT NULL,
  runnable_queue_count INTEGER NOT NULL,
  terminal_status TEXT NOT NULL,
  clean_handback INTEGER NOT NULL,
  outcome TEXT NOT NULL,
  successor_task_id TEXT,
  successor_receipted INTEGER NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capacity_reconfigurations (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  expected_configured_capacity INTEGER NOT NULL,
  requested_configured_capacity INTEGER NOT NULL,
  previous_state_revision INTEGER NOT NULL,
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authority_transfer_steps (
  transfer_id TEXT NOT NULL,
  step TEXT NOT NULL,
  request_id TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (transfer_id, step)
);
CREATE TABLE IF NOT EXISTS federation_members (
  authority_id TEXT PRIMARY KEY,
  transfer_id TEXT NOT NULL,
  configured_capacity INTEGER NOT NULL,
  source_state_revision INTEGER NOT NULL,
  prepare_receipt_sha256 TEXT NOT NULL,
  finalize_receipt_sha256 TEXT,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lifecycle_watchdog (
  task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
  lifecycle_state TEXT NOT NULL,
  worker_status TEXT NOT NULL,
  completion_signals_json TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  remaining_work_json TEXT,
  progress_ref TEXT,
  progress_observed_at TEXT,
  handback_deadline_checks INTEGER NOT NULL,
  handback_deadline_limit INTEGER NOT NULL,
  required_action TEXT NOT NULL,
  interrupt_receipt_id TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lifecycle_watchdog_requests (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lease_expirations (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispatcher_adoptions (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  body_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS setup_failures (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  saga_id TEXT NOT NULL,
  failed_outbox_id TEXT NOT NULL,
  selected_successor_task_id TEXT,
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_timing (
  task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
  estimate_version INTEGER NOT NULL,
  estimated_bucket TEXT NOT NULL,
  current_lane TEXT NOT NULL,
  confidence TEXT NOT NULL,
  task_family TEXT NOT NULL,
  tool_family TEXT NOT NULL,
  environment_class TEXT NOT NULL,
  evidence_basis_json TEXT NOT NULL,
  expected_setup_seconds INTEGER,
  expected_test_seconds INTEGER,
  expected_active_seconds INTEGER,
  expected_external_wait_seconds INTEGER,
  heavyweight_concurrency_cap INTEGER NOT NULL,
  queue_entered_at TEXT NOT NULL,
  started_at TEXT,
  actual_json TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS duration_reclassifications (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  from_bucket TEXT NOT NULL,
  to_bucket TEXT NOT NULL,
  estimate_version INTEGER NOT NULL,
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS duration_progress (
  request_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  result_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS duration_samples (
  sample_id TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
  task_family TEXT NOT NULL,
  tool_family TEXT NOT NULL,
  environment_class TEXT NOT NULL,
  estimated_bucket TEXT NOT NULL,
  actual_bucket TEXT NOT NULL,
  estimate_version INTEGER NOT NULL,
  active_seconds INTEGER NOT NULL,
  queue_seconds INTEGER,
  setup_seconds INTEGER,
  tool_wait_seconds INTEGER,
  external_wait_seconds INTEGER,
  total_wall_seconds INTEGER,
  first_evidence_seconds INTEGER,
  safe_close_seconds INTEGER,
  evidence_refs_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  revision INTEGER NOT NULL,
  occurred_at TEXT NOT NULL,
  task_id TEXT,
  correlation_id TEXT NOT NULL,
  type TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  rule_ids_json TEXT NOT NULL,
  before_state TEXT,
  after_state TEXT,
  metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS legacy_blobs (
  migration_id TEXT PRIMARY KEY,
  original_bytes BLOB NOT NULL,
  warnings_json TEXT NOT NULL,
  imported_at TEXT NOT NULL
);
"""


class Plane:
    def __init__(self, state_dir: Path, ledger_path: Path) -> None:
        self.state_dir = state_dir
        self.db_path = state_dir / "orchestrator.sqlite3"
        self.ledger_path = ledger_path

    def connect(self) -> sqlite3.Connection:
        if self.db_path.exists() and self.db_path.is_symlink():
            fail(
                "STATE_UNSAFE",
                "database cannot be a symlink",
                exit_status=EXIT_STATE,
            )
        previous_umask = os.umask(0o077)
        try:
            connection = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
            try:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("PRAGMA busy_timeout = 5000")
                for suffix in ("", "-wal", "-shm"):
                    state_file = Path(str(self.db_path) + suffix)
                    if not state_file.exists():
                        continue
                    if state_file.is_symlink():
                        fail(
                            "STATE_UNSAFE",
                            "SQLite authority files cannot be symlinks",
                            exit_status=EXIT_STATE,
                        )
                    if (
                        hasattr(os, "getuid")
                        and state_file.stat().st_uid != os.getuid()
                    ):
                        fail(
                            "STATE_OWNERSHIP",
                            "SQLite authority must be owned by the current user",
                            exit_status=EXIT_STATE,
                        )
                    os.chmod(state_file, 0o600)
            except BaseException:
                connection.close()
                raise
        finally:
            os.umask(previous_umask)
        return connection

    def initialize(self, now: str, configured_capacity: int = 4) -> dict[str, Any]:
        timestamp(now)
        bounded_int(
            configured_capacity,
            "configured_capacity",
            1,
            64,
        )
        if self.db_path.exists() and self.db_path.is_symlink():
            fail("STATE_UNSAFE", "database cannot be a symlink", exit_status=EXIT_STATE)
        created = not self.db_path.exists()
        connection = self.connect()
        try:
            connection.executescript(SCHEMA_SQL)
            os.chmod(self.db_path, 0o600)
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM metadata WHERE key='schema_version'").fetchone():
                installed_version = connection.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0]
                if installed_version.split(".", 1)[0] != SCHEMA_VERSION.split(".", 1)[0]:
                    fail("VERSION_UNSUPPORTED", "database schema major version is unsupported")
                connection.execute(
                    "UPDATE metadata SET value=? WHERE key='schema_version'",
                    (SCHEMA_VERSION,),
                )
            else:
                ledger = validate_policy(read_json(str(self.ledger_path)))
                connection.executemany(
                    "INSERT INTO policy_rules(rule_id,rule_revision,body_json) VALUES(?,?,?)",
                    [
                        (rule["id"], rule["rule_revision"], canonical(rule))
                        for rule in ledger["rules"]
                    ],
                )
                values = {
                    "schema_version": SCHEMA_VERSION,
                    "policy_revision": str(ledger["ledger_version"]),
                    "revision": "0",
                    "next_fence": "1",
                    "configured_capacity": str(configured_capacity),
                    "authority_id": f"orc-{secrets.token_hex(16)}",
                    "authority_role": "ROOT",
                    "authority_state": "ACTIVE_ROOT",
                    "authority_epoch": "1",
                    "parent_authority_id": "",
                    "active_transfer_id": "",
                    "created_at": now,
                }
                connection.executemany(
                    "INSERT INTO metadata(key,value) VALUES(?,?)", values.items()
                )
            connection.execute(
                """INSERT OR IGNORE INTO metadata(key,value)
                   VALUES('configured_capacity',?)""",
                (str(configured_capacity),),
            )
            authority_defaults = {
                "authority_id": f"orc-{secrets.token_hex(16)}",
                "authority_role": "ROOT",
                "authority_state": "ACTIVE_ROOT",
                "authority_epoch": "1",
                "parent_authority_id": "",
                "active_transfer_id": "",
            }
            connection.executemany(
                "INSERT OR IGNORE INTO metadata(key,value) VALUES(?,?)",
                authority_defaults.items(),
            )
            connection.execute(
                """INSERT OR IGNORE INTO task_timing(
                  task_id,estimate_version,estimated_bucket,current_lane,
                  confidence,task_family,tool_family,environment_class,
                  evidence_basis_json,expected_setup_seconds,
                  expected_test_seconds,expected_active_seconds,
                  expected_external_wait_seconds,heavyweight_concurrency_cap,
                  queue_entered_at,started_at,actual_json,updated_at
                )
                SELECT task_id,1,'60m+','60m+','low','legacy-unspecified',
                       'unspecified','unspecified',?,NULL,NULL,NULL,NULL,64,
                       created_at,
                       CASE WHEN state='RUNNING' THEN updated_at ELSE NULL END,
                       NULL,?
                FROM tasks""",
                (canonical(["schema-migration-fallback"]), now),
            )
            effective_capacity = int(
                self.metadata(connection, "configured_capacity")
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {
            "created": created,
            "schema_version": SCHEMA_VERSION,
            "configured_capacity": effective_capacity,
        }

    @staticmethod
    def metadata(connection: sqlite3.Connection, key: str) -> str:
        row = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        if not row:
            fail("STATE_CORRUPT", "required database metadata is missing", exit_status=EXIT_STATE)
        return row[0]

    @staticmethod
    def bump_revision(connection: sqlite3.Connection) -> int:
        revision = int(Plane.metadata(connection, "revision")) + 1
        connection.execute(
            "UPDATE metadata SET value=? WHERE key='revision'", (str(revision),)
        )
        return revision

    @staticmethod
    def event(
        connection: sqlite3.Connection,
        now: str,
        task_id: str | None,
        correlation_id: str,
        event_type: str,
        reason_code: str,
        rule_ids: list[str],
        before: str | None,
        after: str | None,
        metadata: dict[str, Any],
    ) -> None:
        revision = Plane.bump_revision(connection)
        reject_sensitive(metadata, "event metadata")
        connection.execute(
            """INSERT INTO events(
              revision,occurred_at,task_id,correlation_id,type,reason_code,
              rule_ids_json,before_state,after_state,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                revision,
                now,
                task_id,
                correlation_id,
                event_type,
                reason_code,
                canonical(rule_ids),
                before,
                after,
                canonical(metadata),
            ),
        )

    def authority(self, connection: sqlite3.Connection) -> dict[str, Any]:
        return {
            "authority_id": self.metadata(connection, "authority_id"),
            "role": self.metadata(connection, "authority_role"),
            "state": self.metadata(connection, "authority_state"),
            "epoch": int(self.metadata(connection, "authority_epoch")),
            "parent_authority_id": (
                self.metadata(connection, "parent_authority_id") or None
            ),
            "active_transfer_id": (
                self.metadata(connection, "active_transfer_id") or None
            ),
        }

    def require_operational_authority(
        self, connection: sqlite3.Connection, operation: str
    ) -> None:
        authority = self.authority(connection)
        state = authority["state"]
        if state in {"SOURCE_PREPARED", "TARGET_STAGED", "SUBORDINATE_PENDING"}:
            fail(
                "AUTHORITY_TRANSFER_FROZEN",
                "authority mutations are frozen during leadership transfer",
                exit_status=EXIT_CONFLICT,
                details={"authority_state": state},
            )
        if state == "ACTIVE_FEDERATION_ROOT" and operation not in {
            "record-policy-rule",
            "classify-decision",
            "migrate-decisions",
            "record-dispatcher-adoption",
        }:
            fail(
                "FEDERATION_SHARD_REQUIRED",
                "capacity-bearing operations must target a subordinate authority",
                exit_status=EXIT_CONFLICT,
            )
        if state == "SUBORDINATE" and operation in {
            "record-policy-rule",
            "classify-decision",
            "migrate-decisions",
        }:
            fail(
                "FEDERATION_ROOT_REQUIRED",
                "PM-proxy policy and decisions belong to the federation root",
                exit_status=EXIT_CONFLICT,
            )
        if state not in {"ACTIVE_ROOT", "ACTIVE_FEDERATION_ROOT", "SUBORDINATE"}:
            fail(
                "AUTHORITY_STATE_INVALID",
                "authority state is not operational",
                exit_status=EXIT_STATE,
            )

    @staticmethod
    def authority_receipt(
        *,
        transfer_id: str,
        phase: str,
        subject_authority_id: str,
        target_authority_id: str,
        authority_epoch: int,
        state_revision: int,
        configured_capacity: int,
        member_authority_ids: list[str],
        membership_digest: str,
        recorded_at: str,
    ) -> dict[str, Any]:
        body = {
            "transfer_id": transfer_id,
            "phase": phase,
            "subject_authority_id": subject_authority_id,
            "target_authority_id": target_authority_id,
            "authority_epoch": authority_epoch,
            "state_revision": state_revision,
            "configured_capacity": configured_capacity,
            "member_authority_ids": sorted(member_authority_ids),
            "membership_digest": membership_digest,
            "recorded_at": recorded_at,
        }
        return {**body, "receipt_sha256": digest(body), "replayed": False}

    @staticmethod
    def transfer_replay(
        connection: sqlite3.Connection,
        transfer_id: str,
        step: str,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """SELECT request_id,request_hash,result_json
               FROM authority_transfer_steps
               WHERE transfer_id=? AND step=?""",
            (transfer_id, step),
        ).fetchone()
        if row is None:
            return None
        if row["request_id"] != request["request_id"] or row[
            "request_hash"
        ] != digest(request):
            fail(
                "AUTHORITY_TRANSFER_CONFLICT",
                "authority transfer step input changed",
                exit_status=EXIT_CONFLICT,
            )
        result = json.loads(row["result_json"])
        result["replayed"] = True
        return result

    @staticmethod
    def record_transfer_step(
        connection: sqlite3.Connection,
        transfer_id: str,
        step: str,
        request: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO authority_transfer_steps(
                 transfer_id,step,request_id,request_hash,result_json,recorded_at
               ) VALUES(?,?,?,?,?,?)""",
            (
                transfer_id,
                step,
                request["request_id"],
                digest(request),
                canonical(result),
                request["now"],
            ),
        )

    @staticmethod
    def set_authority_metadata(
        connection: sqlite3.Connection,
        *,
        role: str,
        state: str,
        epoch: int,
        parent_authority_id: str | None,
        transfer_id: str | None,
    ) -> None:
        values = {
            "authority_role": role,
            "authority_state": state,
            "authority_epoch": str(epoch),
            "parent_authority_id": parent_authority_id or "",
            "active_transfer_id": transfer_id or "",
        }
        connection.executemany(
            "UPDATE metadata SET value=? WHERE key=?",
            [(value, key) for key, value in values.items()],
        )

    def prepare_authority_transfer(self, raw: Any) -> dict[str, Any]:
        request = validate_prepare_authority_transfer(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.transfer_replay(
                connection, request["transfer_id"], "SOURCE_PREPARE", request
            )
            if replay is not None:
                connection.commit()
                return replay
            authority = self.authority(connection)
            revision = int(self.metadata(connection, "revision"))
            if authority["role"] != "ROOT" or authority["state"] != "ACTIVE_ROOT":
                fail(
                    "AUTHORITY_STATE_CONFLICT",
                    "only an active standalone root can prepare transfer",
                    exit_status=EXIT_CONFLICT,
                )
            if authority["authority_id"] == request["target_authority_id"]:
                fail("AUTHORITY_TRANSFER_INVALID", "an authority cannot adopt itself")
            if revision != request["expected_state_revision"]:
                fail(
                    "STATE_REVISION_CONFLICT",
                    "authority state revision changed",
                    exit_status=EXIT_CONFLICT,
                    details={"current_state_revision": revision},
                )
            occupancy = self.active_or_reserved_count(connection)
            if occupancy != 0:
                fail(
                    "AUTHORITY_DRAIN_REQUIRED",
                    "source authority must have no active or reserved workers",
                    exit_status=EXIT_CONFLICT,
                    details={"active_or_reserved_count": occupancy},
                )
            epoch = authority["epoch"] + 1
            self.set_authority_metadata(
                connection,
                role="ROOT",
                state="SOURCE_PREPARED",
                epoch=epoch,
                parent_authority_id=None,
                transfer_id=request["transfer_id"],
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "AUTHORITY_TRANSFER_PREPARED",
                "OWNER_AUTHORIZED_SUCCESSOR",
                ["BR-OWNER-001"],
                "ACTIVE_ROOT",
                "SOURCE_PREPARED",
                {
                    "transfer_id": request["transfer_id"],
                    "source_authority_id": authority["authority_id"],
                    "target_authority_id": request["target_authority_id"],
                    "evidence_refs": request["evidence_refs"],
                },
            )
            capacity = int(self.metadata(connection, "configured_capacity"))
            membership = digest(
                [{"authority_id": authority["authority_id"], "capacity": capacity}]
            )
            result = self.authority_receipt(
                transfer_id=request["transfer_id"],
                phase="SOURCE_PREPARED",
                subject_authority_id=authority["authority_id"],
                target_authority_id=request["target_authority_id"],
                authority_epoch=epoch,
                state_revision=int(self.metadata(connection, "revision")),
                configured_capacity=capacity,
                member_authority_ids=[authority["authority_id"]],
                membership_digest=membership,
                recorded_at=request["now"],
            )
            self.record_transfer_step(
                connection,
                request["transfer_id"],
                "SOURCE_PREPARE",
                request,
                result,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def stage_federation(self, raw: Any) -> dict[str, Any]:
        request = validate_stage_federation(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.transfer_replay(
                connection, request["transfer_id"], "TARGET_STAGE", request
            )
            if replay is not None:
                connection.commit()
                return replay
            authority = self.authority(connection)
            revision = int(self.metadata(connection, "revision"))
            if authority["role"] != "ROOT" or authority["state"] != "ACTIVE_ROOT":
                fail(
                    "AUTHORITY_STATE_CONFLICT",
                    "successor must be an active standalone root",
                    exit_status=EXIT_CONFLICT,
                )
            if revision != request["expected_state_revision"]:
                fail(
                    "STATE_REVISION_CONFLICT",
                    "successor state revision changed",
                    exit_status=EXIT_CONFLICT,
                    details={"current_state_revision": revision},
                )
            if self.active_or_reserved_count(connection) != 0:
                fail(
                    "AUTHORITY_DRAIN_REQUIRED",
                    "successor authority must have no active or reserved workers",
                    exit_status=EXIT_CONFLICT,
                )
            receipts = request["source_receipts"]
            source_ids = [item["subject_authority_id"] for item in receipts]
            if authority["authority_id"] in source_ids:
                fail("AUTHORITY_TRANSFER_INVALID", "successor cannot be a source member")
            for receipt in receipts:
                if (
                    receipt["phase"] != "SOURCE_PREPARED"
                    or receipt["transfer_id"] != request["transfer_id"]
                    or receipt["target_authority_id"] != authority["authority_id"]
                    or receipt["member_authority_ids"]
                    != [receipt["subject_authority_id"]]
                ):
                    fail(
                        "AUTHORITY_RECEIPT_MISMATCH",
                        "source preparation receipt does not target this successor",
                    )
            epoch = authority["epoch"] + 1
            self.set_authority_metadata(
                connection,
                role="ROOT",
                state="TARGET_STAGED",
                epoch=epoch,
                parent_authority_id=None,
                transfer_id=request["transfer_id"],
            )
            for receipt in receipts:
                connection.execute(
                    """INSERT INTO federation_members(
                         authority_id,transfer_id,configured_capacity,
                         source_state_revision,prepare_receipt_sha256,
                         finalize_receipt_sha256,state,created_at,updated_at
                       ) VALUES(?,?,?,?,?,NULL,'STAGED',?,?)""",
                    (
                        receipt["subject_authority_id"],
                        request["transfer_id"],
                        receipt["configured_capacity"],
                        receipt["state_revision"],
                        receipt["receipt_sha256"],
                        request["now"],
                        request["now"],
                    ),
                )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "FEDERATION_STAGED",
                "TWO_PHASE_AUTHORITY_TRANSFER",
                ["BR-OWNER-001"],
                "ACTIVE_ROOT",
                "TARGET_STAGED",
                {
                    "transfer_id": request["transfer_id"],
                    "member_authority_ids": sorted(source_ids),
                    "evidence_refs": request["evidence_refs"],
                },
            )
            membership = digest(
                sorted(receipt["receipt_sha256"] for receipt in receipts)
            )
            result = self.authority_receipt(
                transfer_id=request["transfer_id"],
                phase="TARGET_STAGED",
                subject_authority_id=authority["authority_id"],
                target_authority_id=authority["authority_id"],
                authority_epoch=epoch,
                state_revision=int(self.metadata(connection, "revision")),
                configured_capacity=sum(
                    receipt["configured_capacity"] for receipt in receipts
                ),
                member_authority_ids=source_ids,
                membership_digest=membership,
                recorded_at=request["now"],
            )
            self.record_transfer_step(
                connection,
                request["transfer_id"],
                "TARGET_STAGE",
                request,
                result,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finalize_authority_transfer(self, raw: Any) -> dict[str, Any]:
        request = validate_finalize_authority_transfer(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.transfer_replay(
                connection, request["transfer_id"], "SOURCE_FINALIZE", request
            )
            if replay is not None:
                connection.commit()
                return replay
            authority = self.authority(connection)
            stage = request["target_stage_receipt"]
            if (
                authority["state"] != "SOURCE_PREPARED"
                or authority["active_transfer_id"] != request["transfer_id"]
                or stage["phase"] != "TARGET_STAGED"
                or stage["transfer_id"] != request["transfer_id"]
                or stage["subject_authority_id"] != stage["target_authority_id"]
                or authority["authority_id"] not in stage["member_authority_ids"]
            ):
                fail(
                    "AUTHORITY_RECEIPT_MISMATCH",
                    "target stage receipt does not include this prepared source",
                )
            if self.active_or_reserved_count(connection) != 0:
                fail(
                    "AUTHORITY_DRAIN_REQUIRED",
                    "source changed after preparation and must be reconciled",
                    exit_status=EXIT_CONFLICT,
                )
            epoch = authority["epoch"] + 1
            self.set_authority_metadata(
                connection,
                role="SUBORDINATE",
                state="SUBORDINATE_PENDING",
                epoch=epoch,
                parent_authority_id=stage["target_authority_id"],
                transfer_id=request["transfer_id"],
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "AUTHORITY_ROOT_DEMOTED",
                "TARGET_STAGE_RECEIPT_VERIFIED",
                ["BR-OWNER-001"],
                "SOURCE_PREPARED",
                "SUBORDINATE_PENDING",
                {
                    "transfer_id": request["transfer_id"],
                    "source_authority_id": authority["authority_id"],
                    "target_authority_id": stage["target_authority_id"],
                    "target_stage_receipt_sha256": stage["receipt_sha256"],
                },
            )
            capacity = int(self.metadata(connection, "configured_capacity"))
            result = self.authority_receipt(
                transfer_id=request["transfer_id"],
                phase="SOURCE_FINALIZED",
                subject_authority_id=authority["authority_id"],
                target_authority_id=stage["target_authority_id"],
                authority_epoch=epoch,
                state_revision=int(self.metadata(connection, "revision")),
                configured_capacity=capacity,
                member_authority_ids=[authority["authority_id"]],
                membership_digest=digest(
                    [stage["receipt_sha256"], authority["authority_id"]]
                ),
                recorded_at=request["now"],
            )
            self.record_transfer_step(
                connection,
                request["transfer_id"],
                "SOURCE_FINALIZE",
                request,
                result,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def activate_federation(self, raw: Any) -> dict[str, Any]:
        request = validate_activate_federation(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.transfer_replay(
                connection, request["transfer_id"], "TARGET_ACTIVATE", request
            )
            if replay is not None:
                connection.commit()
                return replay
            authority = self.authority(connection)
            if (
                authority["state"] != "TARGET_STAGED"
                or authority["active_transfer_id"] != request["transfer_id"]
            ):
                fail(
                    "AUTHORITY_STATE_CONFLICT",
                    "target federation is not staged",
                    exit_status=EXIT_CONFLICT,
                )
            receipts = request["source_finalize_receipts"]
            member_rows = list(
                connection.execute(
                    "SELECT * FROM federation_members WHERE transfer_id=? ORDER BY authority_id",
                    (request["transfer_id"],),
                )
            )
            member_ids = [row["authority_id"] for row in member_rows]
            receipt_ids = sorted(
                receipt["subject_authority_id"] for receipt in receipts
            )
            if receipt_ids != member_ids:
                fail(
                    "AUTHORITY_RECEIPT_MISMATCH",
                    "source finalization receipts do not match staged members",
                )
            for receipt in receipts:
                if (
                    receipt["phase"] != "SOURCE_FINALIZED"
                    or receipt["transfer_id"] != request["transfer_id"]
                    or receipt["target_authority_id"] != authority["authority_id"]
                    or receipt["member_authority_ids"]
                    != [receipt["subject_authority_id"]]
                ):
                    fail(
                        "AUTHORITY_RECEIPT_MISMATCH",
                        "source finalization receipt is not valid for this target",
                    )
                connection.execute(
                    """UPDATE federation_members
                       SET finalize_receipt_sha256=?,state='PENDING_ENABLE',updated_at=?
                       WHERE authority_id=? AND transfer_id=?""",
                    (
                        receipt["receipt_sha256"],
                        request["now"],
                        receipt["subject_authority_id"],
                        request["transfer_id"],
                    ),
                )
            epoch = authority["epoch"] + 1
            self.set_authority_metadata(
                connection,
                role="ROOT",
                state="ACTIVE_FEDERATION_ROOT",
                epoch=epoch,
                parent_authority_id=None,
                transfer_id=request["transfer_id"],
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "FEDERATION_ROOT_ACTIVATED",
                "ALL_SOURCES_DEMOTED",
                ["BR-OWNER-001"],
                "TARGET_STAGED",
                "ACTIVE_FEDERATION_ROOT",
                {
                    "transfer_id": request["transfer_id"],
                    "member_authority_ids": member_ids,
                    "evidence_refs": request["evidence_refs"],
                },
            )
            result = self.authority_receipt(
                transfer_id=request["transfer_id"],
                phase="TARGET_ACTIVE",
                subject_authority_id=authority["authority_id"],
                target_authority_id=authority["authority_id"],
                authority_epoch=epoch,
                state_revision=int(self.metadata(connection, "revision")),
                configured_capacity=sum(row["configured_capacity"] for row in member_rows),
                member_authority_ids=member_ids,
                membership_digest=digest(
                    sorted(receipt["receipt_sha256"] for receipt in receipts)
                ),
                recorded_at=request["now"],
            )
            self.record_transfer_step(
                connection,
                request["transfer_id"],
                "TARGET_ACTIVATE",
                request,
                result,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def enable_subordinate(self, raw: Any) -> dict[str, Any]:
        request = validate_enable_subordinate(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.transfer_replay(
                connection, request["transfer_id"], "SOURCE_ENABLE", request
            )
            if replay is not None:
                connection.commit()
                return replay
            authority = self.authority(connection)
            activation = request["target_activation_receipt"]
            if (
                authority["state"] != "SUBORDINATE_PENDING"
                or authority["active_transfer_id"] != request["transfer_id"]
                or activation["phase"] != "TARGET_ACTIVE"
                or activation["transfer_id"] != request["transfer_id"]
                or activation["target_authority_id"]
                != authority["parent_authority_id"]
                or activation["subject_authority_id"]
                != authority["parent_authority_id"]
                or authority["authority_id"]
                not in activation["member_authority_ids"]
            ):
                fail(
                    "AUTHORITY_RECEIPT_MISMATCH",
                    "target activation receipt does not enable this source",
                )
            epoch = authority["epoch"] + 1
            self.set_authority_metadata(
                connection,
                role="SUBORDINATE",
                state="SUBORDINATE",
                epoch=epoch,
                parent_authority_id=authority["parent_authority_id"],
                transfer_id=request["transfer_id"],
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "SUBORDINATE_AUTHORITY_ENABLED",
                "FEDERATION_ROOT_RECEIPT_VERIFIED",
                ["BR-OWNER-001"],
                "SUBORDINATE_PENDING",
                "SUBORDINATE",
                {
                    "transfer_id": request["transfer_id"],
                    "source_authority_id": authority["authority_id"],
                    "target_authority_id": authority["parent_authority_id"],
                    "target_activation_receipt_sha256": activation[
                        "receipt_sha256"
                    ],
                },
            )
            capacity = int(self.metadata(connection, "configured_capacity"))
            result = self.authority_receipt(
                transfer_id=request["transfer_id"],
                phase="SUBORDINATE_ACTIVE",
                subject_authority_id=authority["authority_id"],
                target_authority_id=authority["parent_authority_id"],
                authority_epoch=epoch,
                state_revision=int(self.metadata(connection, "revision")),
                configured_capacity=capacity,
                member_authority_ids=[authority["authority_id"]],
                membership_digest=digest(
                    [activation["receipt_sha256"], authority["authority_id"]]
                ),
                recorded_at=request["now"],
            )
            self.record_transfer_step(
                connection,
                request["transfer_id"],
                "SOURCE_ENABLE",
                request,
                result,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def abort_authority_transfer(self, raw: Any) -> dict[str, Any]:
        request = validate_abort_authority_transfer(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self.transfer_replay(
                connection, request["transfer_id"], "ABORT", request
            )
            if replay is not None:
                connection.commit()
                return replay
            authority = self.authority(connection)
            if (
                authority["state"] not in {"SOURCE_PREPARED", "TARGET_STAGED"}
                or authority["active_transfer_id"] != request["transfer_id"]
                or request["expected_authority_state"] != authority["state"]
            ):
                fail(
                    "AUTHORITY_STATE_CONFLICT",
                    "only an uncommitted prepared or staged transfer may abort",
                    exit_status=EXIT_CONFLICT,
                )
            if int(self.metadata(connection, "revision")) != request[
                "expected_state_revision"
            ]:
                fail(
                    "STATE_REVISION_CONFLICT",
                    "authority state revision changed",
                    exit_status=EXIT_CONFLICT,
                )
            if request["target_activation_absent"] is not True:
                fail(
                    "AUTHORITY_ABORT_DENIED",
                    "abort requires owner-verified absence of target activation",
                )
            if authority["state"] == "TARGET_STAGED":
                connection.execute(
                    "DELETE FROM federation_members WHERE transfer_id=?",
                    (request["transfer_id"],),
                )
            epoch = authority["epoch"] + 1
            self.set_authority_metadata(
                connection,
                role="ROOT",
                state="ACTIVE_ROOT",
                epoch=epoch,
                parent_authority_id=None,
                transfer_id=None,
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "AUTHORITY_TRANSFER_ABORTED",
                request["reason_code"],
                ["BR-OWNER-001"],
                authority["state"],
                "ACTIVE_ROOT",
                {
                    "transfer_id": request["transfer_id"],
                    "authority_id": authority["authority_id"],
                    "evidence_refs": request["evidence_refs"],
                },
            )
            result = self.authority_receipt(
                transfer_id=request["transfer_id"],
                phase="ABORTED",
                subject_authority_id=authority["authority_id"],
                target_authority_id=authority["authority_id"],
                authority_epoch=epoch,
                state_revision=int(self.metadata(connection, "revision")),
                configured_capacity=int(
                    self.metadata(connection, "configured_capacity")
                ),
                member_authority_ids=[],
                membership_digest=digest([]),
                recorded_at=request["now"],
            )
            self.record_transfer_step(
                connection,
                request["transfer_id"],
                "ABORT",
                request,
                result,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def rules(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        return [
            validate_rule(json.loads(row[0]))
            for row in connection.execute(
                """SELECT p.body_json
                   FROM policy_rules p
                   JOIN (
                     SELECT rule_id,MAX(rule_revision) AS rule_revision
                     FROM policy_rules GROUP BY rule_id
                   ) latest
                   ON latest.rule_id=p.rule_id
                   AND latest.rule_revision=p.rule_revision
                   ORDER BY p.rule_id"""
            )
        ]

    def record_rule(self, raw: Any) -> dict[str, Any]:
        request = validate_policy_update(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "record-policy-rule")
            request_hash = digest(request)
            existing = connection.execute(
                "SELECT request_hash,result_json FROM policy_updates WHERE request_id=?",
                (request["request_id"],),
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "policy update request_id input changed",
                        exit_status=EXIT_CONFLICT,
                    )
                connection.commit()
                return json.loads(existing["result_json"])
            current_policy_revision = int(
                self.metadata(connection, "policy_revision")
            )
            if request["expected_policy_revision"] != current_policy_revision:
                fail(
                    "POLICY_REVISION_CONFLICT",
                    "policy ledger revision changed",
                    exit_status=EXIT_CONFLICT,
                    details={"current_policy_revision": current_policy_revision},
                )
            rule = request["rule"]
            previous = connection.execute(
                "SELECT MAX(rule_revision) FROM policy_rules WHERE rule_id=?",
                (rule["id"],),
            ).fetchone()[0]
            if previous is not None and rule["rule_revision"] <= previous:
                fail(
                    "POLICY_RULE_REVISION_CONFLICT",
                    "rule revision must increase monotonically",
                    exit_status=EXIT_CONFLICT,
                )
            connection.execute(
                "INSERT INTO policy_rules(rule_id,rule_revision,body_json) VALUES(?,?,?)",
                (rule["id"], rule["rule_revision"], canonical(rule)),
            )
            new_policy_revision = current_policy_revision + 1
            connection.execute(
                "UPDATE metadata SET value=? WHERE key='policy_revision'",
                (str(new_policy_revision),),
            )
            result = {
                "rule_id": rule["id"],
                "rule_revision": rule["rule_revision"],
                "policy_revision": new_policy_revision,
                "state": rule["state"],
            }
            connection.execute(
                "INSERT INTO policy_updates VALUES(?,?,?,?,?,?)",
                (
                    request["request_id"],
                    request_hash,
                    rule["id"],
                    rule["rule_revision"],
                    canonical(result),
                    request["now"],
                ),
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "POLICY_RULE_RECORDED",
                "TYPED_SCOPED_RULE",
                [rule["id"]],
                str(current_policy_revision),
                str(new_policy_revision),
                {
                    "rule_id": rule["id"],
                    "rule_revision": rule["rule_revision"],
                    "source_kind": rule["provenance"]["source_kind"],
                },
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def bounded_metadata_int(
        connection: sqlite3.Connection,
        key: str,
        low: int,
        high: int,
    ) -> int:
        raw = Plane.metadata(connection, key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            fail(
                "STATE_CORRUPT",
                "required integer metadata is invalid",
                exit_status=EXIT_STATE,
                details={"metadata_key": key},
            )
        if str(value) != raw or not low <= value <= high:
            fail(
                "STATE_CORRUPT",
                "required integer metadata is outside its canonical bound",
                exit_status=EXIT_STATE,
                details={"metadata_key": key},
            )
        return value

    @staticmethod
    def validate_capacity_receipt(
        committed: Any,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        fields = {
            "request_id",
            "previous_configured_capacity",
            "configured_capacity",
            "previous_state_revision",
            "committed_state_revision",
            "active_or_reserved_count_at_commit",
        }
        if not isinstance(committed, dict) or set(committed) != fields:
            fail(
                "STATE_CORRUPT",
                "capacity reconfiguration receipt is corrupt",
                exit_status=EXIT_STATE,
            )
        integer_fields = fields - {"request_id"}
        if any(
            isinstance(committed[field], bool)
            or not isinstance(committed[field], int)
            for field in integer_fields
        ):
            fail(
                "STATE_CORRUPT",
                "capacity reconfiguration receipt is corrupt",
                exit_status=EXIT_STATE,
            )
        if (
            committed["request_id"] != request["request_id"]
            or committed["previous_configured_capacity"]
            != request["expected_configured_capacity"]
            or committed["configured_capacity"]
            != request["requested_configured_capacity"]
            or committed["previous_state_revision"]
            != request["expected_state_revision"]
            or committed["committed_state_revision"]
            != committed["previous_state_revision"] + 1
            or not 1 <= committed["previous_configured_capacity"] <= 64
            or not 1 <= committed["configured_capacity"] <= 64
            or not 0
            <= committed["previous_state_revision"]
            < committed["committed_state_revision"]
            <= 9_223_372_036_854_775_807
            or not 0
            <= committed["active_or_reserved_count_at_commit"]
            <= committed["configured_capacity"]
        ):
            fail(
                "STATE_CORRUPT",
                "capacity reconfiguration receipt is internally inconsistent",
                exit_status=EXIT_STATE,
            )
        return committed

    def configure_capacity(self, raw: Any) -> dict[str, Any]:
        request = validate_capacity_reconfiguration(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "configure-capacity")
            request_hash = digest(request)
            existing = connection.execute(
                """SELECT request_hash,result_json
                   FROM capacity_reconfigurations WHERE request_id=?""",
                (request["request_id"],),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "capacity reconfiguration request_id input changed",
                        exit_status=EXIT_CONFLICT,
                    )
                try:
                    committed = json.loads(existing["result_json"])
                except (TypeError, json.JSONDecodeError):
                    fail(
                        "STATE_CORRUPT",
                        "capacity reconfiguration receipt is corrupt",
                        exit_status=EXIT_STATE,
                    )
                committed = self.validate_capacity_receipt(committed, request)
                current_capacity = self.bounded_metadata_int(
                    connection, "configured_capacity", 1, 64
                )
                current_revision = self.bounded_metadata_int(
                    connection, "revision", 0, 9_223_372_036_854_775_807
                )
                connection.commit()
                return {
                    **committed,
                    "replayed": True,
                    "current_configured_capacity": current_capacity,
                    "current_state_revision": current_revision,
                }

            current_capacity = self.bounded_metadata_int(
                connection, "configured_capacity", 1, 64
            )
            current_revision = self.bounded_metadata_int(
                connection, "revision", 0, 9_223_372_036_854_775_807
            )
            if request["expected_state_revision"] != current_revision:
                fail(
                    "STATE_REVISION_CONFLICT",
                    "capacity reconfiguration state revision is stale",
                    exit_status=EXIT_CONFLICT,
                    details={"current_state_revision": current_revision},
                )
            if request["expected_configured_capacity"] != current_capacity:
                fail(
                    "CAPACITY_CONFIGURATION_CONFLICT",
                    "configured capacity changed from the expected value",
                    exit_status=EXIT_CONFLICT,
                    details={"current_configured_capacity": current_capacity},
                )
            active_or_reserved = self.active_or_reserved_count(connection)
            if request["requested_configured_capacity"] < active_or_reserved:
                fail(
                    "CAPACITY_BELOW_OCCUPANCY",
                    "configured capacity cannot be reduced below active or reserved occupancy",
                    exit_status=EXIT_CONFLICT,
                    details={"active_or_reserved_count": active_or_reserved},
                )
            connection.execute(
                "UPDATE metadata SET value=? WHERE key='configured_capacity'",
                (str(request["requested_configured_capacity"]),),
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "CAPACITY_RECONFIGURED",
                "TYPED_EXPECTED_CURRENT_CHANGE",
                ["BR-LAUNCH-001"],
                str(current_capacity),
                str(request["requested_configured_capacity"]),
                {
                    "active_or_reserved_count": active_or_reserved,
                    "evidence_refs": request["evidence_refs"],
                    "expected_state_revision": current_revision,
                },
            )
            committed_revision = self.bounded_metadata_int(
                connection, "revision", 0, 9_223_372_036_854_775_807
            )
            committed = {
                "request_id": request["request_id"],
                "previous_configured_capacity": current_capacity,
                "configured_capacity": request["requested_configured_capacity"],
                "previous_state_revision": current_revision,
                "committed_state_revision": committed_revision,
                "active_or_reserved_count_at_commit": active_or_reserved,
            }
            connection.execute(
                """INSERT INTO capacity_reconfigurations(
                  request_id,request_hash,expected_configured_capacity,
                  requested_configured_capacity,previous_state_revision,
                  result_json,recorded_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    request["request_id"],
                    request_hash,
                    request["expected_configured_capacity"],
                    request["requested_configured_capacity"],
                    current_revision,
                    canonical(committed),
                    request["now"],
                ),
            )
            connection.commit()
            return {
                **committed,
                "replayed": False,
                "current_configured_capacity": request[
                    "requested_configured_capacity"
                ],
                "current_state_revision": committed_revision,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def current_claims(self, connection: sqlite3.Connection) -> list[sqlite3.Row]:
        return connection.execute(
            "SELECT * FROM owner_claims WHERE status='active' ORDER BY canonical_resource_key"
        ).fetchall()

    def next_fence(self, connection: sqlite3.Connection) -> int:
        fence = int(self.metadata(connection, "next_fence"))
        connection.execute(
            "UPDATE metadata SET value=? WHERE key='next_fence'", (str(fence + 1),)
        )
        return fence

    def reserve_launch(
        self,
        connection: sqlite3.Connection,
        request: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        requested_duration = request["duration_estimate"]
        if (
            requested_duration["estimated_bucket"] in HEAVY_BUCKETS
            and requested_duration["evidence_basis"]
            != ["compatibility-fallback"]
        ):
            heavyweight_reserved = connection.execute(
                """SELECT count(*) FROM task_timing AS timing
                   JOIN tasks AS task ON task.task_id=timing.task_id
                   WHERE timing.current_lane IN ('45m','60m+')
                     AND task.state IN ('LAUNCH_PENDING','RUNNING')"""
            ).fetchone()[0]
            if (
                heavyweight_reserved
                >= requested_duration["heavyweight_concurrency_cap"]
            ):
                fail(
                    "HEAVYWEIGHT_CAP",
                    "heavyweight lane capacity is already active or reserved",
                    exit_status=EXIT_CONFLICT,
                    details={
                        "active_or_reserved": heavyweight_reserved,
                        "cap": requested_duration[
                            "heavyweight_concurrency_cap"
                        ],
                    },
                )
        existing = connection.execute(
            """SELECT task_id,state FROM tasks
               WHERE source_event_key=? OR idempotency_key=? OR outcome_key=?""",
            (
                request["source_event_key"],
                request["idempotency_key"],
                request["outcome_key"],
            ),
        ).fetchone()
        if existing:
            self.event(
                connection,
                request["now"],
                existing["task_id"],
                request["request_id"],
                "DUPLICATE_STOP",
                "DUPLICATE_IDENTITY",
                ["BR-DUP-001", "BR-OWNER-001"],
                None,
                "DUPLICATE_STOP",
                {"proposed_task_id": request["task_id"]},
            )
            fail(
                "DUPLICATE_STOP",
                "source event, idempotency key, or outcome already has a logical task",
                exit_status=EXIT_CONFLICT,
                details={"canonical_task_id": existing["task_id"]},
            )
        configured_capacity = int(
            self.metadata(connection, "configured_capacity")
        )
        active_or_reserved = self.active_or_reserved_count(connection)
        if active_or_reserved >= configured_capacity:
            fail(
                "CAPACITY_FULL",
                "configured worker capacity is already active or reserved",
                exit_status=EXIT_CONFLICT,
                details={
                    "configured_capacity": configured_capacity,
                    "active_or_reserved_count": active_or_reserved,
                },
            )
        blocked = connection.execute(
            "SELECT task_id,priority,block_json FROM tasks WHERE state='BLOCKED'"
        ).fetchall()
        due = []
        for row in blocked:
            block = json.loads(row["block_json"])
            if block.get("audit_required") and row["priority"] >= request["priority"]:
                due.append(row["task_id"])
        if due:
            fail(
                "BLOCKED_REAUDIT_REQUIRED",
                "blocked work must be re-audited before lower-value launch",
                exit_status=EXIT_CONFLICT,
                details={"task_ids": sorted(due)},
            )
        target = request["target"]
        for claim in self.current_claims(connection):
            claimed_target = json.loads(claim["target_json"])
            if targets_overlap(target, claimed_target):
                fail(
                    "OWNERSHIP_CONFLICT",
                    "repository target already has a canonical owner",
                    exit_status=EXIT_CONFLICT,
                    details={
                        "canonical_task_id": claim["task_id"],
                        "claim_id": claim["claim_id"],
                    },
                )
        rules, excluded = resolve_rules(
            self.rules(connection), request["context"], request["now"]
        )
        policy_revision = int(self.metadata(connection, "policy_revision"))
        fence = self.next_fence(connection)
        lease_epoch = 1
        rule_ids = [rule["id"] for rule in rules]
        claim_id = f"claim:{digest([request['task_id'], target['canonical_key']])[:24]}"
        duration = request["duration_estimate"]
        appendix = {
            "envelope_version": INTERFACE_VERSION,
            "task_id": request["task_id"],
            "source_event_key": request["source_event_key"],
            "idempotency_key": request["idempotency_key"],
            "outcome_key": request["outcome_key"],
            "issued_at": request["now"],
            "policy_snapshot_revision": policy_revision,
            "lease_epoch": lease_epoch,
            "fencing_token": fence,
            "owner_claim_id": claim_id,
            "target": {
                "remote": target["remote"],
                "path": target["path"],
                "base_sha": target["base_sha"],
            },
            "permissions": request["permissions"],
            "prohibitions": request["prohibitions"],
            "effective_rules": [
                {
                    "rule_id": rule["id"],
                    "revision": rule["rule_revision"],
                    "directive": rule["directive"],
                    "why": rule["why"],
                }
                for rule in rules
            ],
            "excluded_rules": excluded,
            "owner_gate_matrix": {
                "PM_PROXY": sorted(ACTION_TYPES - set(ACTION_GATE_MAP)),
                "OWNER_GATE": sorted(GATES - {"NONE"}),
                "DENY": [
                    "unknown-schema-or-action",
                    "unresolved-policy-conflict",
                    "stale-fence-or-envelope",
                    "secret-or-prompt-injection-authority",
                ],
            },
            "privacy_boundary": request["privacy_boundary"],
            "dependencies": request["dependencies"],
            "evidence_contract": request["evidence_contract"],
            "cleanup_duty": request["cleanup_duty"],
            "duration_estimate": duration,
            **(
                {"public_metadata": request["public_metadata"]}
                if "public_metadata" in request
                else {}
            ),
            "duration_protocol": {
                "progress_command": "record-duration-progress",
                "observation_command": "record-duration-observation",
                "blocked_waiting_are_non_runtime": True,
                "reclassification_preserves_worker": True,
            },
            "heartbeat_protocol": {
                "command": "record-heartbeat",
                "requires_current_fence": True,
            },
            "closure_protocol": {
                "command": "record-handback",
                "archive_receipt_command": "record-archive-receipt",
                "lifecycle_watchdog_command": "lifecycle-watchdog",
                "handback_deadline_checks": HANDBACK_DEADLINE_CHECKS,
                "reconcile_after": [
                    "worker-message",
                    "wait-timeout",
                    "before-status-claim",
                ],
                "requires_current_fence": True,
            },
            "runtime_policy": {
                "root": {
                    "model": REQUIRED_ROOT_MODEL,
                    "reasoning_effort": REQUIRED_ROOT_REASONING_EFFORT,
                    "service_tier": REQUIRED_SERVICE_TIER,
                    "fast_mode": REQUIRED_FAST_MODE,
                },
                "worker_defaults": {
                    "model": REQUIRED_ROOT_MODEL,
                    "reasoning_effort": REQUIRED_ROOT_REASONING_EFFORT,
                    "service_tier": REQUIRED_SERVICE_TIER,
                    "fast_mode": REQUIRED_FAST_MODE,
                },
                "history": {
                    "full_history_requires_verified_parent": True,
                },
                "tier_truth": {
                    "accepted_attestation_sources": [
                        "config-verified",
                        "runtime",
                    ],
                    "config_verified_is_not_runtime_attested": True,
                    "desired_performance_multiplier": FAST_PERFORMANCE_MULTIPLIER,
                    "gpt56_standard_credit_multiplier": GPT56_STANDARD_CREDIT_MULTIPLIER,
                },
            },
            "receipt_required": {
                "task_id": request["task_id"],
                "policy_snapshot_revision": policy_revision,
                "applicable_rule_ids": rule_ids,
                "lease_epoch": lease_epoch,
                "fencing_token": fence,
                "duration_estimate": duration,
                "runtime_policy": {
                    "root_model": REQUIRED_ROOT_MODEL,
                    "root_reasoning_effort": REQUIRED_ROOT_REASONING_EFFORT,
                    "root_service_tier": REQUIRED_SERVICE_TIER,
                    "root_fast_mode": REQUIRED_FAST_MODE,
                    "worker_model": REQUIRED_ROOT_MODEL,
                    "worker_reasoning_effort": REQUIRED_ROOT_REASONING_EFFORT,
                    "worker_service_tier": REQUIRED_SERVICE_TIER,
                    "worker_fast_mode": REQUIRED_FAST_MODE,
                    "service_tier_attestation_allowed": [
                        "config-verified",
                        "runtime",
                    ],
                    "parent_attestation_required": True,
                },
            },
        }
        stored_envelope = dict(appendix)
        envelope_json = canonical(stored_envelope)
        connection.execute(
            """INSERT INTO tasks(
              task_id,source_event_key,idempotency_key,outcome_key,state,priority,
              dependencies_json,target_json,prompt_reference,policy_revision,
              applicable_rule_ids_json,lease_epoch,fencing_token,created_at,
              updated_at,source
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request["task_id"],
                request["source_event_key"],
                request["idempotency_key"],
                request["outcome_key"],
                "LAUNCH_PENDING",
                request["priority"],
                canonical(request["dependencies"]),
                canonical(target),
                request["source_event_key"],
                policy_revision,
                canonical(rule_ids),
                lease_epoch,
                fence,
                request["now"],
                request["now"],
                source,
            ),
        )
        connection.execute(
            """INSERT INTO owner_claims(
              claim_id,canonical_resource_key,target_json,task_id,lease_epoch,
              fencing_token,status,acquired_at,heartbeat_at,expires_at
            ) VALUES(?,?,?,?,?,?,'active',?,?,?)""",
            (
                claim_id,
                target["canonical_key"],
                canonical(target),
                request["task_id"],
                lease_epoch,
                fence,
                request["now"],
                request["now"],
                request["lease_expires_at"],
            ),
        )
        outbox_id = f"create:{request['idempotency_key']}"
        connection.execute(
            """INSERT INTO outbox(
              outbox_id,kind,idempotency_key,task_id,payload_json,state,attempts,
              created_at,updated_at
            ) VALUES(?,?,?,? ,?,'pending',0,?,?)""",
            (
                outbox_id,
                "CREATE_THREAD",
                request["idempotency_key"],
                request["task_id"],
                canonical(
                    {
                        "task_id": request["task_id"],
                        "source_event_key": request["source_event_key"],
                        "envelope": stored_envelope,
                    }
                ),
                request["now"],
                request["now"],
            ),
        )
        connection.execute(
            "INSERT INTO launches(request_id,request_hash,task_id,envelope_json,issued_at) VALUES(?,?,?,?,?)",
            (
                request["request_id"],
                digest(
                    {
                        key: value
                        for key, value in request.items()
                        if key != "prompt"
                    }
                ),
                request["task_id"],
                envelope_json,
                request["now"],
            ),
        )
        expected = duration["expected_components"]
        expected_active = (
            None
            if expected["setup_seconds"] is None
            or expected["test_seconds"] is None
            else expected["setup_seconds"] + expected["test_seconds"]
        )
        connection.execute(
            """INSERT INTO task_timing(
              task_id,estimate_version,estimated_bucket,current_lane,confidence,
              task_family,tool_family,environment_class,evidence_basis_json,
              expected_setup_seconds,expected_test_seconds,
              expected_active_seconds,expected_external_wait_seconds,
              heavyweight_concurrency_cap,queue_entered_at,started_at,
              actual_json,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?)""",
            (
                request["task_id"],
                duration["estimate_version"],
                duration["estimated_bucket"],
                duration["estimated_bucket"],
                duration["confidence"],
                duration["task_family"],
                duration["tool_family"],
                duration["environment_class"],
                canonical(duration["evidence_basis"]),
                expected["setup_seconds"],
                expected["test_seconds"],
                expected_active,
                expected["remote_wait_seconds"],
                duration["heavyweight_concurrency_cap"],
                request["now"],
                request["now"],
            ),
        )
        self.event(
            connection,
            request["now"],
            request["task_id"],
            request["request_id"],
            "TASK_PREFLIGHT",
            "PREFLIGHT_PASSED",
            rule_ids,
            "DRAFT",
            "PREFLIGHT",
            {},
        )
        self.event(
            connection,
            request["now"],
            request["task_id"],
            request["request_id"],
            "OWNER_CLAIM_RESERVED",
            "CANONICAL_OWNER_ACQUIRED",
            ["BR-OWNER-001", "BR-DUP-001"],
            "PREFLIGHT",
            "RESERVED",
            {"claim_id": claim_id},
        )
        self.event(
            connection,
            request["now"],
            request["task_id"],
            request["request_id"],
            "LAUNCH_OUTBOX_ENQUEUED",
            "CREATE_THREAD_PENDING",
            ["BR-LAUNCH-001"],
            "RESERVED",
            "LAUNCH_PENDING",
            {"claim_id": claim_id, "outbox_id": outbox_id},
        )
        return {
            "envelope": appendix,
            "prompt": (
                request["prompt"]
                + "\n\n<orchestrator_launch_envelope>\n"
                + canonical(appendix)
                + "\n</orchestrator_launch_envelope>"
            ),
            "outbox": {"outbox_id": outbox_id, "kind": "CREATE_THREAD"},
        }

    def prepare_launch(self, raw: Any) -> dict[str, Any]:
        request = validate_prepare(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "prepare-launch")
            result = self.reserve_launch(connection, request, source="prepare-launch")
            connection.commit()
            return result
        except ControlError as error:
            if error.code == "DUPLICATE_STOP":
                connection.commit()
            else:
                connection.rollback()
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def classify_root_action(self, raw: Any) -> dict[str, Any]:
        guard = load_root_role_guard()
        try:
            response = guard.classify_action(raw)
        except guard.GuardInputError as error:
            fail(error.code, str(error))

        result = response["result"]
        authority_connection = self.connect()
        try:
            authority = self.authority(authority_connection)
        finally:
            authority_connection.close()
        if authority["state"] in {
            "SOURCE_PREPARED",
            "TARGET_STAGED",
            "SUBORDINATE_PENDING",
        }:
            result.update(
                {
                    "decision": "DENY",
                    "reason_code": "AUTHORITY_TRANSFER_FROZEN",
                    "required_action": "COMPLETE_OR_ABORT_AUTHORITY_TRANSFER",
                    "owner_notification_authorized": False,
                }
            )
        if (
            raw.get("action_type") == "notify_owner"
            and result["decision"] == "ALLOW"
        ):
            evidence = next(
                (
                    item
                    for item in raw.get("evidence", [])
                    if item.get("kind") == "owner_gate"
                    and item.get("verified") is True
                    and item.get("route") == "OWNER_GATE"
                    and item.get("owner_prompt_required") is True
                ),
                None,
            )
            verified = False
            if evidence is not None:
                connection = self.connect()
                try:
                    decision = connection.execute(
                        """SELECT request_id,route,gate_fingerprint
                           FROM decisions WHERE request_id=?""",
                        (evidence["decision_request_id"],),
                    ).fetchone()
                    if decision and decision["route"] == "OWNER_GATE":
                        first = connection.execute(
                            """SELECT request_id FROM decisions
                               WHERE gate_fingerprint=?
                               ORDER BY recorded_at,request_id LIMIT 1""",
                            (decision["gate_fingerprint"],),
                        ).fetchone()
                        verified = bool(
                            first
                            and first["request_id"] == decision["request_id"]
                            and (
                                evidence.get("gate_fingerprint") is None
                                or evidence["gate_fingerprint"]
                                == decision["gate_fingerprint"]
                            )
                        )
                finally:
                    connection.close()
            if not verified:
                result.update(
                    {
                        "decision": "DENY",
                        "reason_code": "VERIFIED_OWNER_GATE_REQUIRED",
                        "required_action": "PROVIDE_OWNER_GATE_EVIDENCE",
                        "owner_notification_authorized": False,
                    }
                )

        try:
            guard.record_evaluation(
                raw,
                response,
                state_file=self.state_dir / "root-role-audit.json",
            )
        except guard.GuardInputError as error:
            fail(error.code, str(error), exit_status=EXIT_STATE)
        return result

    def classify(self, raw: Any) -> dict[str, Any]:
        request = validate_classify(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "classify-decision")
            existing = connection.execute(
                "SELECT * FROM decisions WHERE request_id=?", (request["request_id"],)
            ).fetchone()
            request_hash = digest(request)
            if existing:
                if existing["request_hash"] != request_hash:
                    fail("IDEMPOTENCY_CONFLICT", "request_id input changed", exit_status=EXIT_CONFLICT)
                result = {
                    "classification": existing["route"],
                    "reason_code": existing["reason_code"],
                    "rule_ids": json.loads(existing["rule_ids_json"]),
                    "reasons": [existing["explanation"]],
                    "owner_prompt_required": existing["route"] == "OWNER_GATE",
                    "notification_deduplicated": True,
                }
                connection.commit()
                return result
            current_policy_revision = int(
                self.metadata(connection, "policy_revision")
            )
            if request["policy_snapshot_revision"] != current_policy_revision:
                fail(
                    "POLICY_REVISION_CONFLICT",
                    "decision context uses a stale policy revision",
                    exit_status=EXIT_CONFLICT,
                    details={"current_policy_revision": current_policy_revision},
                )
            rules, _ = resolve_rules(self.rules(connection), request["context"], request["now"])
            if request["gate_type"] != "NONE":
                allowed_gates = ACTION_GATE_MAP.get(request["action_type"], set())
                if request["gate_type"] not in allowed_gates:
                    fail(
                        "DECISION_DENIED",
                        "typed action and owner-gate code do not agree",
                    )
                matched = [
                    rule
                    for rule in rules
                    if rule["effect"] == "require_owner"
                    and rule["gate_code"] in {request["gate_type"], "ANY_ENUMERATED"}
                ]
                if not matched:
                    fail("DECISION_DENIED", "owner gate is not mapped by effective policy")
                route = "OWNER_GATE"
                reason = f"ENUMERATED_{request['gate_type']}"
                ids = [rule["id"] for rule in matched]
            elif request["action_type"] == "HOSTED_CI_BILLING_BLOCK":
                matched = [
                    rule
                    for rule in rules
                    if rule["id"] in {"BR-CI-001", "BR-PM-001"}
                ]
                route = "PM_PROXY"
                reason = "HOSTED_CI_UNEXECUTED_INFRASTRUCTURE"
                ids = [rule["id"] for rule in matched]
            elif request["action_type"] in ACTION_GATE_MAP:
                fail(
                    "DECISION_DENIED",
                    "typed exceptional action requires its enumerated owner gate",
                )
            elif (
                request["authorized"]
                and request["reversible"]
                and not request["destructive"]
                and not request["external_effect"]
                and not request["auto_publish"]
                and not request["identity_change"]
                and not request["credential_needed"]
                and not request["cost_change"]
                and not request["force_or_admin"]
            ):
                matched = [rule for rule in rules if rule["effect"] == "allow_pm_proxy"]
                route = "PM_PROXY"
                reason = "AUTHORIZED_REVERSIBLE_ROUTINE"
                ids = [rule["id"] for rule in matched]
            else:
                fail(
                    "DECISION_DENIED",
                    "unknown or unsafe decision is denied to the orchestrator, not promoted to an owner prompt",
                )
            fingerprint = digest(
                [
                    route,
                    request["gate_type"],
                    request["target_alias"],
                    request["authorization_scope"],
                    request["policy_snapshot_revision"],
                    request["state_revision"],
                ]
            )
            duplicate = connection.execute(
                "SELECT 1 FROM decisions WHERE gate_fingerprint=?", (fingerprint,)
            ).fetchone() is not None
            connection.execute(
                """INSERT INTO decisions(
                  request_id,request_hash,route,reason_code,rule_ids_json,
                  explanation,gate_fingerprint,recorded_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    request["request_id"],
                    request_hash,
                    route,
                    reason,
                    canonical(ids),
                    reason.replace("_", " ").lower(),
                    fingerprint,
                    request["now"],
                ),
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "DECISION_CLASSIFIED",
                reason,
                ids,
                None,
                route,
                {"notification_deduplicated": duplicate},
            )
            connection.commit()
            return {
                "classification": route,
                "reason_code": reason,
                "rule_ids": ids,
                "reasons": [reason.replace("_", " ").lower()],
                "owner_prompt_required": route == "OWNER_GATE" and not duplicate,
                "notification_deduplicated": duplicate,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def launch_receipt(self, raw: Any) -> dict[str, Any]:
        request = validate_receipt(raw, "launch")
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "record-launch-receipt")
            existing_task = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (request["task_id"],)
            ).fetchone()
            if (
                existing_task
                and existing_task["state"] == "RUNNING"
                and existing_task["external_thread_id"] == request["external_thread_id"]
                and existing_task["policy_revision"]
                == request["policy_snapshot_revision"]
                and existing_task["lease_epoch"] == request["lease_epoch"]
                and existing_task["fencing_token"] == request["fencing_token"]
                and sorted(json.loads(existing_task["applicable_rule_ids_json"]))
                == sorted(request["applicable_rule_ids"])
            ):
                self.record_capacity_receipt(connection, request)
                timing = connection.execute(
                    "SELECT * FROM task_timing WHERE task_id=?",
                    (request["task_id"],),
                ).fetchone()
                connection.commit()
                return {
                    "task_id": request["task_id"],
                    "state": "RUNNING",
                    "runtime_attestation": request["runtime_attestation"],
                    "duration_estimate": (
                        self.duration_result(timing) if timing else None
                    ),
                }
            task = self.checked_task(connection, request, {"LAUNCH_PENDING"})
            expected_ids = json.loads(task["applicable_rule_ids_json"])
            if sorted(request["applicable_rule_ids"]) != sorted(expected_ids):
                fail("RULE_RECEIPT_MISMATCH", "launch receipt omitted applicable rules")
            connection.execute(
                "UPDATE tasks SET state='RUNNING',external_thread_id=?,updated_at=? WHERE task_id=?",
                (request["external_thread_id"], request["now"], request["task_id"]),
            )
            connection.execute(
                """UPDATE task_timing SET started_at=COALESCE(started_at,?),
                   updated_at=? WHERE task_id=?""",
                (request["now"], request["now"], request["task_id"]),
            )
            timing = connection.execute(
                "SELECT * FROM task_timing WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            duration_receipt = self.duration_result(timing) if timing else None
            connection.execute(
                "UPDATE launches SET receipt_json=? WHERE task_id=?",
                (
                    canonical(
                        {
                            **request,
                            "duration_estimate": duration_receipt,
                        }
                    ),
                    request["task_id"],
                ),
            )
            connection.execute(
                "UPDATE outbox SET state='completed',updated_at=? WHERE task_id=? AND kind='CREATE_THREAD'",
                (request["now"], request["task_id"]),
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["request_id"],
                "LAUNCH_RECEIPT",
                "EXTERNAL_THREAD_CONFIRMED",
                expected_ids,
                "LAUNCH_PENDING",
                "RUNNING",
                {
                    "external_thread_id": request["external_thread_id"],
                    "runtime_attestation": request["runtime_attestation"],
                },
            )
            self.record_capacity_receipt(connection, request)
            connection.commit()
            return {
                "task_id": request["task_id"],
                "state": "RUNNING",
                "runtime_attestation": request["runtime_attestation"],
                "duration_estimate": duration_receipt,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def active_or_reserved_count(connection: sqlite3.Connection) -> int:
        return connection.execute(
            """SELECT count(*) FROM tasks AS task
               JOIN owner_claims AS claim ON claim.task_id=task.task_id
               WHERE claim.status='active'
                 AND task.state IN ('LAUNCH_PENDING','RUNNING')"""
        ).fetchone()[0]

    @staticmethod
    def active_and_reserved_counts(
        connection: sqlite3.Connection,
    ) -> tuple[int, int]:
        row = connection.execute(
            """SELECT
                 sum(CASE WHEN task.state='RUNNING' THEN 1 ELSE 0 END) AS active,
                 sum(CASE WHEN task.state='LAUNCH_PENDING' THEN 1 ELSE 0 END) AS reserved
               FROM tasks AS task
               JOIN owner_claims AS claim ON claim.task_id=task.task_id
               WHERE claim.status='active'
                 AND task.state IN ('LAUNCH_PENDING','RUNNING')"""
        ).fetchone()
        return int(row["active"] or 0), int(row["reserved"] or 0)

    def capacity_result(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, Any]:
        active_count, reserved_count = self.active_and_reserved_counts(connection)
        active = active_count + reserved_count
        runnable = row["runnable_queue_count"]
        configured = row["configured_capacity"]
        successor_state = None
        if row["successor_task_id"]:
            successor = connection.execute(
                """SELECT task.state FROM tasks AS task
                   JOIN owner_claims AS claim ON claim.task_id=task.task_id
                   WHERE task.task_id=? AND claim.status='active'""",
                (row["successor_task_id"],),
            ).fetchone()
            successor_state = None if successor is None else successor["state"]
        exact_successor_satisfied = (
            row["outcome"] == "SUCCESSOR_RESERVED"
            and successor_state in {"LAUNCH_PENDING", "RUNNING"}
        ) or (
            row["outcome"] == "SUCCESSOR_RECEIPTED"
            and bool(row["successor_receipted"])
            and successor_state == "RUNNING"
        )
        deficit = (
            runnable > 0
            and not exact_successor_satisfied
            and active != configured
        )
        return {
            "saga_id": row["saga_id"],
            "configured_capacity": configured,
            "runnable_queue_count": runnable,
            "active_or_reserved_count": active,
            "active_count": active_count,
            "reserved_setup_count": reserved_count,
            "outcome": row["outcome"],
            "successor_task_id": row["successor_task_id"],
            "successor_receipted": bool(row["successor_receipted"]),
            "terminal_status": row["terminal_status"],
            "clean_handback": bool(row["clean_handback"]),
            "failure_state": "CAPACITY_INVARIANT_FAILED" if deficit else None,
            "evidence_refs": json.loads(row["evidence_refs_json"]),
            "updated_at": row["updated_at"],
        }

    def record_capacity_receipt(
        self, connection: sqlite3.Connection, request: dict[str, Any]
    ) -> None:
        row = connection.execute(
            "SELECT * FROM capacity_sagas WHERE successor_task_id=?",
            (request["task_id"],),
        ).fetchone()
        if not row:
            return
        if row["successor_receipted"]:
            return
        active = self.active_or_reserved_count(connection)
        successor = connection.execute(
            """SELECT 1 FROM tasks AS task
               JOIN owner_claims AS claim ON claim.task_id=task.task_id
               WHERE task.task_id=? AND claim.status='active'
                 AND task.state='RUNNING'""",
            (request["task_id"],),
        ).fetchone()
        outcome = "SUCCESSOR_RECEIPTED" if successor else "CAPACITY_DEFICIT"
        connection.execute(
            """UPDATE capacity_sagas
               SET successor_receipted=1,outcome=?,updated_at=?
               WHERE saga_id=?""",
            (outcome, request["now"], row["saga_id"]),
        )
        self.event(
            connection,
            request["now"],
            request["task_id"],
            row["saga_id"],
            (
                "CAPACITY_REFILL_SATISFIED"
                if outcome == "SUCCESSOR_RECEIPTED"
                else "CAPACITY_DEFICIT"
            ),
            outcome,
            ["BR-CLOSE-001", "BR-LAUNCH-001"],
            "LAUNCH_PENDING",
            "RUNNING",
            {
                "configured_capacity": row["configured_capacity"],
                "runnable_queue_count": row["runnable_queue_count"],
                "active_or_reserved_count": active,
            },
        )

    @staticmethod
    def duration_result(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "estimate_version": row["estimate_version"],
            "estimated_bucket": row["estimated_bucket"],
            "current_lane": row["current_lane"],
            "confidence": row["confidence"],
            "task_family": row["task_family"],
            "tool_family": row["tool_family"],
            "environment_class": row["environment_class"],
            "evidence_basis": json.loads(row["evidence_basis_json"]),
            "expected_components": {
                "setup_seconds": row["expected_setup_seconds"],
                "test_seconds": row["expected_test_seconds"],
                "remote_wait_seconds": row["expected_external_wait_seconds"],
            },
            "heavyweight_concurrency_cap": row["heavyweight_concurrency_cap"],
            "queue_entered_at": row["queue_entered_at"],
            "started_at": row["started_at"],
            "actual": (
                None if row["actual_json"] is None else json.loads(row["actual_json"])
            ),
            "updated_at": row["updated_at"],
        }

    def record_duration_progress(self, raw: Any) -> dict[str, Any]:
        request = validate_duration_progress(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "record-duration-progress")
            sanitized_hash = digest(
                {
                    key: value
                    for key, value in request.items()
                    if key != "successor_request"
                }
                | {
                    "successor_identity": (
                        None
                        if request["successor_request"] is None
                        else {
                            key: request["successor_request"][key]
                            for key in (
                                "request_id",
                                "task_id",
                                "source_event_key",
                                "idempotency_key",
                                "outcome_key",
                            )
                        }
                    )
                }
            )
            existing = connection.execute(
                "SELECT * FROM duration_progress WHERE request_id=?",
                (request["request_id"],),
            ).fetchone()
            if existing:
                if existing["request_hash"] != sanitized_hash:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "duration progress request_id input changed",
                        exit_status=EXIT_CONFLICT,
                    )
                connection.commit()
                return json.loads(existing["result_json"])
            task = self.checked_task(connection, request, {"RUNNING", "BLOCKED"})
            self.require_external_receipt(connection, request)
            timing = connection.execute(
                "SELECT * FROM task_timing WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            if not timing:
                fail(
                    "DURATION_STATE_MISSING",
                    "task has no durable duration estimate",
                    exit_status=EXIT_STATE,
                )
            previous_actual = (
                {}
                if timing["actual_json"] is None
                else json.loads(timing["actual_json"])
            )
            for key in (
                "active_seconds",
                "queue_seconds",
                "setup_seconds",
                "tool_wait_seconds",
                "external_wait_seconds",
                "total_wall_seconds",
                "first_evidence_seconds",
            ):
                before = previous_actual.get(key)
                after = request[key]
                if before is not None and after is not None and after < before:
                    fail(
                        "DURATION_NON_MONOTONIC",
                        f"{key} cannot decrease",
                        exit_status=EXIT_CONFLICT,
                    )
            from_bucket = timing["current_lane"]
            to_bucket = from_bucket
            reason_codes: list[str] = []
            successor = None
            active_seconds = request["active_seconds"]
            if request["runtime_state"] == "active":
                measured_bucket = bucket_for_seconds(active_seconds)
                from_index = duration_index(from_bucket)
                measured_index = duration_index(measured_bucket)
                if measured_index > from_index:
                    to_bucket = measured_bucket
                    reason_codes.append("NEXT_BUCKET_CROSSED")
                    if measured_index - from_index >= 2:
                        reason_codes.append("TWO_BUCKETS_SKIPPED")
                expected_active = timing["expected_active_seconds"]
                if (
                    expected_active is not None
                    and active_seconds > max(1, expected_active) * 2
                    and from_index < len(DURATION_BUCKETS) - 1
                ):
                    to_bucket = DURATION_BUCKETS[
                        max(duration_index(to_bucket), from_index + 1)
                    ]
                    reason_codes.append("ESTIMATE_ERROR_OVER_2X")
            reclassified = to_bucket != from_bucket
            new_version = timing["estimate_version"]
            if reclassified:
                new_version += 1
                replacement_expected = max(
                    active_seconds,
                    (
                        DURATION_LIMITS[to_bucket]
                        if to_bucket != "60m+"
                        else active_seconds * 2
                    ),
                )
                connection.execute(
                    """UPDATE task_timing SET estimate_version=?,current_lane=?,
                       expected_active_seconds=?,actual_json=?,updated_at=?
                       WHERE task_id=?""",
                    (
                        new_version,
                        to_bucket,
                        replacement_expected,
                        canonical(request["actual"]),
                        request["now"],
                        request["task_id"],
                    ),
                )
                if request["successor_request"] is not None:
                    successor = self.reserve_launch(
                        connection,
                        request["successor_request"],
                        source="duration-reclassification",
                    )
                result = {
                    "task_id": request["task_id"],
                    "reclassified": True,
                    "worker_restart_required": False,
                    "ownership_preserved": True,
                    "lease_epoch": task["lease_epoch"],
                    "fencing_token": task["fencing_token"],
                    "from_bucket": from_bucket,
                    "to_bucket": to_bucket,
                    "estimate_version": new_version,
                    "released_lane": from_bucket,
                    "reason_codes": sorted(set(reason_codes)),
                    "successor": successor,
                }
                connection.execute(
                    """INSERT INTO duration_reclassifications(
                      request_id,request_hash,task_id,from_bucket,to_bucket,
                      estimate_version,result_json,recorded_at
                    ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        request["request_id"],
                        sanitized_hash,
                        request["task_id"],
                        from_bucket,
                        to_bucket,
                        new_version,
                        canonical(result),
                        request["now"],
                    ),
                )
                self.event(
                    connection,
                    request["now"],
                    request["task_id"],
                    request["request_id"],
                    "DURATION_LANE_RECLASSIFIED",
                    sorted(set(reason_codes))[0],
                    ["BR-LAUNCH-001", "BR-OWNER-001"],
                    from_bucket,
                    to_bucket,
                    {
                        "active_seconds": active_seconds,
                        "estimate_version": new_version,
                        "released_lane": from_bucket,
                        "successor_task_id": (
                            None
                            if request["successor_request"] is None
                            else request["successor_request"]["task_id"]
                        ),
                    },
                )
            else:
                if request["successor_request"] is not None:
                    fail(
                        "SUCCESSOR_NOT_ALLOWED",
                        "a successor may be reserved only by an actual lane reclassification",
                        exit_status=EXIT_CONFLICT,
                    )
                connection.execute(
                    """UPDATE task_timing SET actual_json=?,updated_at=?
                       WHERE task_id=?""",
                    (
                        canonical(request["actual"]),
                        request["now"],
                        request["task_id"],
                    ),
                )
                result = {
                    "task_id": request["task_id"],
                    "reclassified": False,
                    "worker_restart_required": False,
                    "ownership_preserved": True,
                    "lease_epoch": task["lease_epoch"],
                    "fencing_token": task["fencing_token"],
                    "from_bucket": from_bucket,
                    "to_bucket": from_bucket,
                    "estimate_version": new_version,
                    "released_lane": None,
                    "reason_codes": (
                        ["NON_RUNTIME_WAIT_EXCLUDED"]
                        if request["runtime_state"] in NON_RUNTIME_STATES
                        else []
                    ),
                    "successor": None,
                }
            connection.execute(
                "INSERT INTO duration_progress VALUES(?,?,?,?,?)",
                (
                    request["request_id"],
                    sanitized_hash,
                    request["task_id"],
                    canonical(result),
                    request["now"],
                ),
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_duration_observation(self, raw: Any) -> dict[str, Any]:
        request = validate_duration_observation(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(
                connection, "record-duration-observation"
            )
            request_hash = digest(request)
            existing = connection.execute(
                "SELECT * FROM duration_samples WHERE sample_id=?",
                (request["sample_id"],),
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "duration sample_id input changed",
                        exit_status=EXIT_CONFLICT,
                    )
                timing = connection.execute(
                    "SELECT * FROM task_timing WHERE task_id=?",
                    (request["task_id"],),
                ).fetchone()
                connection.commit()
                return {
                    "task_id": request["task_id"],
                    "sample_id": request["sample_id"],
                    "actual_bucket": existing["actual_bucket"],
                    "early_finish": duration_index(existing["actual_bucket"])
                    < duration_index(existing["estimated_bucket"]),
                    "duration": self.duration_result(timing),
                }
            prior_task_sample = connection.execute(
                "SELECT sample_id FROM duration_samples WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            if prior_task_sample:
                fail(
                    "DURATION_SAMPLE_EXISTS",
                    "a completed task contributes at most one calibration sample",
                    exit_status=EXIT_CONFLICT,
                    details={"sample_id": prior_task_sample["sample_id"]},
                )
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            if not task:
                fail("TASK_NOT_FOUND", "task does not exist")
            if (
                request["policy_snapshot_revision"] != task["policy_revision"]
                or request["lease_epoch"] != task["lease_epoch"]
                or request["fencing_token"] != task["fencing_token"]
            ):
                fail("STALE_FENCE", "duration observation has stale fencing")
            self.require_external_receipt(connection, request)
            timing = connection.execute(
                "SELECT * FROM task_timing WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            if not timing:
                fail("DURATION_STATE_MISSING", "task has no duration state")
            actual_bucket = bucket_for_seconds(request["active_seconds"])
            early = duration_index(actual_bucket) < duration_index(
                timing["estimated_bucket"]
            )
            connection.execute(
                """INSERT INTO duration_samples(
                  sample_id,request_hash,task_id,task_family,tool_family,
                  environment_class,estimated_bucket,actual_bucket,
                  estimate_version,active_seconds,queue_seconds,setup_seconds,
                  tool_wait_seconds,external_wait_seconds,total_wall_seconds,
                  first_evidence_seconds,safe_close_seconds,evidence_refs_json,
                  recorded_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    request["sample_id"],
                    request_hash,
                    request["task_id"],
                    timing["task_family"],
                    timing["tool_family"],
                    timing["environment_class"],
                    timing["estimated_bucket"],
                    actual_bucket,
                    timing["estimate_version"],
                    request["active_seconds"],
                    request["queue_seconds"],
                    request["setup_seconds"],
                    request["tool_wait_seconds"],
                    request["external_wait_seconds"],
                    request["total_wall_seconds"],
                    request["first_evidence_seconds"],
                    request["safe_close_seconds"],
                    canonical(request["evidence_refs"]),
                    request["now"],
                ),
            )
            connection.execute(
                "UPDATE task_timing SET actual_json=?,updated_at=? WHERE task_id=?",
                (
                    canonical(request["actual"]),
                    request["now"],
                    request["task_id"],
                ),
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["sample_id"],
                (
                    "DURATION_EARLY_FINISH"
                    if early
                    else "DURATION_COMPLETED_SAMPLE"
                ),
                (
                    "ACTUAL_SHORTER_THAN_ESTIMATE"
                    if early
                    else "COMPLETED_CALIBRATION_EVIDENCE"
                ),
                ["BR-EVIDENCE-001"],
                timing["estimated_bucket"],
                actual_bucket,
                {
                    "active_seconds": request["active_seconds"],
                    "estimate_version": timing["estimate_version"],
                    "evidence_count": len(request["evidence_refs"]),
                },
            )
            updated = connection.execute(
                "SELECT * FROM task_timing WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            connection.commit()
            return {
                "task_id": request["task_id"],
                "sample_id": request["sample_id"],
                "actual_bucket": actual_bucket,
                "early_finish": early,
                "duration": self.duration_result(updated),
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def duration_estimate(self, raw: Any) -> dict[str, Any]:
        request = validate_duration_estimate_query(raw)
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT * FROM duration_samples
                   WHERE task_family=? AND tool_family=? AND environment_class=?
                   ORDER BY recorded_at DESC,sample_id DESC LIMIT ?""",
                (
                    request["task_family"],
                    request["tool_family"],
                    request["environment_class"],
                    MAX_CALIBRATION_SAMPLES,
                ),
            ).fetchall()
            if len(rows) < MIN_CALIBRATION_SAMPLES:
                return {
                    "state": "SPARSE_EVIDENCE",
                    "automatic": False,
                    "confidence": "low",
                    "completed_sample_count": len(rows),
                    "minimum_required": MIN_CALIBRATION_SAMPLES,
                    "estimate": None,
                }
            counts = {
                bucket: sum(row["actual_bucket"] == bucket for row in rows)
                for bucket in DURATION_BUCKETS
            }
            highest = max(counts.values())
            leaders = [bucket for bucket, count in counts.items() if count == highest]
            if len(leaders) != 1 or highest * 5 < len(rows) * 3:
                return {
                    "state": "CONFLICTING_EVIDENCE",
                    "automatic": False,
                    "confidence": "low",
                    "completed_sample_count": len(rows),
                    "minimum_required": MIN_CALIBRATION_SAMPLES,
                    "estimate": None,
                }
            active = sorted(row["active_seconds"] for row in rows)
            median = active[len(active) // 2]
            bucket = bucket_for_seconds(median)
            return {
                "state": "LEARNED_PRIOR_AVAILABLE",
                "automatic": True,
                "confidence": "high" if len(rows) >= 10 else "moderate",
                "completed_sample_count": len(rows),
                "minimum_required": MIN_CALIBRATION_SAMPLES,
                "estimate": {
                    "estimate_version": request["minimum_estimate_version"],
                    "estimated_bucket": bucket,
                    "task_family": request["task_family"],
                    "tool_family": request["tool_family"],
                    "environment_class": request["environment_class"],
                    "evidence_basis": [
                        f"completed-samples-{len(rows)}",
                        "bounded-rolling-median",
                    ],
                    "median_active_seconds": median,
                },
            }
        finally:
            connection.close()

    @staticmethod
    def duration_schedule(raw: Any) -> dict[str, Any]:
        request = validate_duration_schedule(raw)
        eligible = []
        deferred = []
        queued_setup_reserved = 0
        failed_setup_rollbacks = 0
        holds = list(request["resource_holds"])
        holds.extend(
            {
                "holder_id": candidate["candidate_id"],
                "state": "queued_setup",
                "resource_profile": candidate["resource_profile"],
            }
            for candidate in request["candidates"]
            if candidate["setup_state"] == "queued_setup"
        )
        heavy_exclusive_groups = {
            hold["resource_profile"]["exclusive_group"]
            for hold in holds
            if hold["resource_profile"]["resource_class"] == "heavy"
            and hold["resource_profile"]["exclusive_group"] is not None
        }
        heavy_resource_holds = sum(
            hold["resource_profile"]["resource_class"] == "heavy"
            for hold in holds
        )
        resource_weights: dict[str, int] = {}
        resource_caps: dict[str, int] = {}
        for hold in holds:
            profile = hold["resource_profile"]
            pool = (
                profile["exclusive_group"]
                or f"class-{profile['resource_class']}"
            )
            resource_weights[pool] = (
                resource_weights.get(pool, 0) + profile["weight"]
            )
            resource_caps[pool] = min(
                resource_caps.get(pool, profile["cap"]), profile["cap"]
            )
        for candidate in request["candidates"]:
            if candidate["setup_state"] == "queued_setup":
                queued_setup_reserved += 1
                deferred.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "reason_code": "QUEUED_SETUP_RESERVED_NOT_ACTIVE",
                    }
                )
                continue
            if candidate["setup_state"] == "failed":
                failed_setup_rollbacks += 1
                deferred.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "reason_code": "SETUP_FAILED_RESERVATION_ROLLED_BACK",
                    }
                )
                continue
            if candidate["runtime_state"] in NON_RUNTIME_STATES:
                deferred.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "reason_code": "NON_RUNTIME_STATE",
                    }
                )
                continue
            profile = candidate["resource_profile"]
            if (
                (
                    candidate["bucket"] in HEAVY_BUCKETS
                    or profile["resource_class"] == "heavy"
                )
                and max(request["active_heavyweight"], heavy_resource_holds)
                >= request["heavyweight_concurrency_cap"]
            ):
                deferred.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "reason_code": "HEAVYWEIGHT_CAP",
                    }
                )
                continue
            if (
                profile["resource_class"] == "heavy"
                and profile["exclusive_group"] is not None
                and profile["exclusive_group"] in heavy_exclusive_groups
            ):
                deferred.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "reason_code": "HEAVY_EXCLUSIVE_GROUP_HELD",
                    }
                )
                continue
            pool = (
                profile["exclusive_group"]
                or f"class-{profile['resource_class']}"
            )
            effective_cap = min(
                profile["cap"], resource_caps.get(pool, profile["cap"])
            )
            if resource_weights.get(pool, 0) + profile["weight"] > effective_cap:
                deferred.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "reason_code": "RESOURCE_WEIGHT_CAP",
                    }
                )
                continue
            score = candidate["priority"] * 100 + min(
                candidate["queue_seconds"] // 60, 100_000
            )
            eligible.append((candidate, score))
        eligible.sort(
            key=lambda item: (
                -item[1],
                -item[0]["queue_seconds"],
                item[0]["candidate_id"],
            )
        )
        short = [
            item for item in eligible if item[0]["bucket"] in SHORT_BUCKETS
        ]
        selected = (
            (
                short[0]
                if request["short_lane_available"] and short
                else (eligible[0] if eligible else None)
            )
            if request["capacity_deficit"]
            else None
        )
        ranked = [
            {
                "rank": index + 1,
                "candidate_id": item[0]["candidate_id"],
                "bucket": item[0]["bucket"],
                "score": item[1],
                "aged_seconds": item[0]["queue_seconds"],
                "resource_profile": item[0]["resource_profile"],
            }
            for index, item in enumerate(eligible)
        ]
        return {
            "selected_candidate_id": (
                None if selected is None else selected[0]["candidate_id"]
            ),
            "selected_resource_profile": (
                None if selected is None else selected[0]["resource_profile"]
            ),
            "outcome": (
                "SELECTED"
                if selected is not None
                else (
                    "EMPTY"
                    if request["capacity_deficit"]
                    else "CAPACITY_FULL"
                )
            ),
            "dispatch_required": selected is not None,
            "owner_prompt_required": False,
            "dispatch_contract": (
                "CALLER_MUST_EXECUTE_RECEIPT_BACKED_PREPARE"
                if selected is not None
                else (
                    "NO_DISPATCH_EMPTY"
                    if request["capacity_deficit"]
                    else "NO_DISPATCH_CAPACITY_FULL"
                )
            ),
            "selected_reason": (
                "SHORT_LANE_ANTI_STARVATION"
                if selected is not None
                and request["short_lane_available"]
                and selected[0]["bucket"] in SHORT_BUCKETS
                else (
                    "FAIR_AGED_VALUE"
                    if selected is not None
                    else (
                        "NO_ELIGIBLE"
                        if request["capacity_deficit"]
                        else "CAPACITY_FULL"
                    )
                )
            ),
            "ranked_eligible": ranked,
            "deferred": sorted(deferred, key=lambda item: item["candidate_id"]),
            "reservation_summary": {
                "queued_setup_reserved_count": queued_setup_reserved,
                "queued_setup_active_count": 0,
                "failed_setup_rollback_count": failed_setup_rollbacks,
                "resource_held_queued_count": sum(
                    hold["state"] == "queued_setup" for hold in holds
                ),
                "resource_held_queued_weight": sum(
                    hold["resource_profile"]["weight"]
                    for hold in holds
                    if hold["state"] == "queued_setup"
                ),
                "active_resource_weight": sum(
                    hold["resource_profile"]["weight"]
                    for hold in holds
                    if hold["state"] == "active"
                ),
                "heavy_resource_active_or_reserved_count": heavy_resource_holds,
                "root_excluded_from_logical_capacity": True,
                "process_oversubscription_inferred": False,
            },
        }

    def checked_task(
        self, connection: sqlite3.Connection, request: dict[str, Any], states: set[str]
    ) -> sqlite3.Row:
        task = connection.execute(
            "SELECT * FROM tasks WHERE task_id=?", (request["task_id"],)
        ).fetchone()
        if not task:
            fail("TASK_NOT_FOUND", "task does not exist")
        if task["state"] not in states:
            fail("TASK_STATE_INVALID", "task state rejects this operation", exit_status=EXIT_CONFLICT)
        if (
            request["policy_snapshot_revision"] != task["policy_revision"]
            or request["lease_epoch"] != task["lease_epoch"]
            or request["fencing_token"] != task["fencing_token"]
        ):
            fail("STALE_FENCE", "policy revision, lease epoch, or fencing token is stale")
        claim = connection.execute(
            "SELECT 1 FROM owner_claims WHERE task_id=? AND status='active' AND fencing_token=?",
            (request["task_id"], request["fencing_token"]),
        ).fetchone()
        if not claim:
            fail("STALE_FENCE", "active ownership claim is missing")
        return task

    @staticmethod
    def require_external_receipt(
        connection: sqlite3.Connection, request: dict[str, Any]
    ) -> str:
        launch = connection.execute(
            "SELECT receipt_json FROM launches WHERE task_id=?",
            (request["task_id"],),
        ).fetchone()
        if not launch or not launch["receipt_json"]:
            fail(
                "EXTERNAL_RECEIPT_REQUIRED",
                "worker mutation requires a canonical external launch receipt",
            )
        canonical_external_id = json.loads(launch["receipt_json"])[
            "external_thread_id"
        ]
        if request.get("external_thread_id") != canonical_external_id:
            fail(
                "EXTERNAL_RECEIPT_MISMATCH",
                "only the receipt-backed external task may mutate",
                exit_status=EXIT_CONFLICT,
                details={"canonical_external_thread_id": canonical_external_id},
            )
        return canonical_external_id

    def record_handback(self, raw: Any) -> dict[str, Any]:
        request = validate_handback(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "record-handback")
            existing = connection.execute(
                "SELECT * FROM handbacks WHERE handback_id=?", (request["handback_id"],)
            ).fetchone()
            request_hash = digest(
                {
                    "handback_id": request["handback_id"],
                    "task_id": request["task_id"],
                    "policy_snapshot_revision": request["policy_snapshot_revision"],
                    "lease_epoch": request["lease_epoch"],
                    "fencing_token": request["fencing_token"],
                    "external_thread_id": request["external_thread_id"],
                    "disposition": request["disposition"],
                    "public_metadata": request.get("public_metadata"),
                    "successor_task_id": (
                        request["successor_request"]["task_id"]
                        if request["successor_request"]
                        else None
                    ),
                    "capacity": {
                        key: request["capacity"][key]
                        for key in (
                            "configured_capacity",
                            "runnable_queue_count",
                            "terminal_status",
                            "clean_handback",
                            "empty_outcome",
                        )
                    },
                    "blocked_audits": [
                        {
                            "task_id": audit["task_id"],
                            "classification": audit["classification"],
                            "outcome": audit["outcome"],
                            "reason_code": audit["reason_code"],
                        }
                        for audit in request["capacity"]["blocked_audits"]
                    ],
                }
            )
            if existing:
                if existing["request_hash"] != request_hash:
                    fail("IDEMPOTENCY_CONFLICT", "handback_id input changed", exit_status=EXIT_CONFLICT)
                replay = json.loads(existing["result_json"])
                if replay.get("successor") and request["successor_request"]:
                    replay["successor"]["prompt"] = (
                        request["successor_request"]["prompt"]
                        + "\n\n<orchestrator_launch_envelope>\n"
                        + canonical(replay["successor"]["envelope"])
                        + "\n</orchestrator_launch_envelope>"
                    )
                connection.commit()
                return replay
            task = self.checked_task(connection, request, {"RUNNING", "BLOCKED", "FAILED"})
            self.require_external_receipt(connection, request)
            before = task["state"]
            active_before_release = self.active_or_reserved_count(connection)
            predecessor_occupied_slot = before == "RUNNING"
            if request["disposition"] == "blocked":
                if request["successor_request"] is not None:
                    fail("SCHEMA_INVALID", "blocked handback cannot create a successor")
                block = {
                    **request["block"],
                    "audit_required": True,
                    "blocked_at": request["now"],
                }
                result = {
                    "task_id": request["task_id"],
                    "state": "BLOCKED",
                    "audit_required": True,
                }
                connection.execute(
                    "UPDATE tasks SET state='BLOCKED',block_json=?,updated_at=? WHERE task_id=?",
                    (canonical(block), request["now"], request["task_id"]),
                )
                stored = {
                    "disposition": "blocked",
                    "public_metadata": request.get("public_metadata"),
                    "check_results": [item["result"] for item in request["checks"]],
                    "hosted_ci": request["hosted_ci"],
                    "resource_dispositions": [item["disposition"] for item in request["resources"]],
                }
                connection.execute(
                    "INSERT INTO handbacks VALUES(?,?,?,?,?,?)",
                    (
                        request["handback_id"],
                        request_hash,
                        request["task_id"],
                        canonical(stored),
                        canonical(result),
                        request["now"],
                    ),
                )
                self.event(
                    connection,
                    request["now"],
                    request["task_id"],
                    request["handback_id"],
                    "TASK_BLOCKED",
                    request["block"]["classification"],
                    ["BR-BLOCK-001"],
                    before,
                    "BLOCKED",
                    {"reason_code": request["block"]["reason_code"]},
                )
                connection.commit()
                return result
            capacity = request["capacity"]
            connection.execute(
                """UPDATE owner_claims SET status='released',heartbeat_at=?
                   WHERE task_id=? AND status='active'""",
                (request["now"], request["task_id"]),
            )
            audit_result = self.recycle_blocked_in_transaction(
                connection,
                audits=capacity["blocked_audits"],
                now=request["now"],
                request_id=f"{request['handback_id']}:blocked-audit",
            )
            successor_result = None
            if request["successor_request"] is not None:
                successor = validate_prepare(request["successor_request"])
                successor_result = self.reserve_launch(
                    connection, successor, source="handback-successor"
                )
            active_claim_ids = {
                row[0]
                for row in connection.execute(
                    "SELECT claim_id FROM owner_claims WHERE task_id=?",
                    (request["task_id"],),
                )
            }
            if not active_claim_ids.intersection(
                item["id"] for item in request["resources"]
            ):
                fail(
                    "CLEANUP_OWNERSHIP_UNPROVEN",
                    "terminal handback must disposition its registered owner claim",
                )
            closure = {
                "disposition": request["disposition"],
                "exact_refs": request["exact_refs"],
                "checks": [
                    {"name": item["name"], "result": item["result"]}
                    for item in request["checks"]
                ],
                "review_finding_count": len(request["review_findings"]),
                "hosted_ci": request["hosted_ci"],
                "deployment_state": request["deployment_state"],
                "artifact_count": len(request["artifacts"]),
                "resources": [
                    {
                        "id": item["id"],
                        "disposition": item["disposition"],
                        "bytes": item["bytes"],
                    }
                    for item in request["resources"]
                ],
                "dependency_count": len(request["dependencies"]),
                "next_action_recorded": bool(request["next_action"]),
            }
            connection.execute(
                "UPDATE tasks SET state='ARCHIVE_PENDING',closure_json=?,updated_at=? WHERE task_id=?",
                (canonical(closure), request["now"], request["task_id"]),
            )
            connection.execute(
                """UPDATE lifecycle_watchdog SET
                   lifecycle_state='COMPLETED',worker_status='completed',
                   required_action='ARCHIVE',remaining_work_json=NULL,
                   progress_ref=NULL,progress_observed_at=NULL,updated_at=?
                   WHERE task_id=?""",
                (request["now"], request["task_id"]),
            )
            active = self.active_or_reserved_count(connection)
            if capacity["runnable_queue_count"] > 0:
                expected_active = min(
                    capacity["configured_capacity"],
                    active_before_release
                    - int(predecessor_occupied_slot)
                    + 1,
                )
            else:
                expected_active = active
            if capacity["runnable_queue_count"] > 0 and active != expected_active:
                fail(
                    "REFILL_PROOF_REQUIRED",
                    "terminal handback cannot release capacity until recycle preserves the exact receipt-backed occupancy",
                    exit_status=EXIT_CONFLICT,
                    details={
                        "configured_capacity": capacity["configured_capacity"],
                        "active_or_reserved_before_release": active_before_release,
                        "expected_active_or_reserved_count": expected_active,
                        "active_or_reserved_count": active,
                    },
                )
            if (
                capacity["runnable_queue_count"] == 0
                and request["successor_request"] is not None
            ):
                fail(
                    "CAPACITY_EVIDENCE_CONFLICT",
                    "zero runnable work cannot carry a successor reservation",
                    exit_status=EXIT_CONFLICT,
                )
            if (
                capacity["empty_outcome"] == "OWNER_GATED"
                and not audit_result["owner_gated_task_ids"]
            ):
                fail(
                    "OWNER_GATE_EVIDENCE_REQUIRED",
                    "OWNER_GATED capacity requires an authority-derived blocked audit",
                    exit_status=EXIT_CONFLICT,
                )
            if request["successor_request"] is not None:
                capacity_outcome = "SUCCESSOR_RESERVED"
            elif capacity["runnable_queue_count"] == 0:
                capacity_outcome = capacity["empty_outcome"]
            elif active == capacity["configured_capacity"]:
                capacity_outcome = "CAPACITY_FULL"
            else:
                capacity_outcome = "CAPACITY_DEFICIT"
            connection.execute(
                """INSERT INTO capacity_sagas(
                  saga_id,task_id,configured_capacity,runnable_queue_count,
                  terminal_status,clean_handback,outcome,successor_task_id,
                  successor_receipted,evidence_refs_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,0,?,?,?)""",
                (
                    request["handback_id"],
                    request["task_id"],
                    capacity["configured_capacity"],
                    capacity["runnable_queue_count"],
                    capacity["terminal_status"],
                    int(capacity["clean_handback"]),
                    capacity_outcome,
                    (
                        request["successor_request"]["task_id"]
                        if request["successor_request"]
                        else None
                    ),
                    canonical(capacity["evidence_refs"]),
                    request["now"],
                    request["now"],
                ),
            )
            capacity_row = connection.execute(
                "SELECT * FROM capacity_sagas WHERE saga_id=?",
                (request["handback_id"],),
            ).fetchone()
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["handback_id"],
                "CAPACITY_RELEASED",
                capacity_outcome,
                ["BR-CLOSE-001", "BR-RESOURCE-001"],
                before,
                "ARCHIVE_PENDING",
                {
                    "configured_capacity": capacity["configured_capacity"],
                    "runnable_queue_count": capacity["runnable_queue_count"],
                    "active_or_reserved_count": active,
                    "successor_task_id": (
                        request["successor_request"]["task_id"]
                        if request["successor_request"]
                        else None
                    ),
                    "blocked_audit_request_id": (
                        f"{request['handback_id']}:blocked-audit"
                    ),
                    "blocked_resume_task_id": audit_result["selected_task_id"],
                },
            )
            archive_outbox = f"archive:{request['task_id']}"
            connection.execute(
                """INSERT OR IGNORE INTO outbox(
                  outbox_id,kind,idempotency_key,task_id,payload_json,state,attempts,
                  created_at,updated_at
                ) VALUES(?, 'ARCHIVE_THREAD', ?, ?, ?, 'pending', 0, ?, ?)""",
                (
                    archive_outbox,
                    archive_outbox,
                    request["task_id"],
                    canonical(
                        {
                            "task_id": request["task_id"],
                            "external_thread_id": task["external_thread_id"],
                        }
                    ),
                    request["now"],
                    request["now"],
                ),
            )
            result = {
                "task_id": request["task_id"],
                "state": "ARCHIVE_PENDING",
                "archive_outbox_id": archive_outbox,
                "successor": successor_result,
                "capacity": self.capacity_result(connection, capacity_row),
                "evidence_count": len(request["checks"]) + len(request["exact_refs"]),
                "resource_count": len(request["resources"]),
                "reclaimed_bytes": sum(
                    item.get("bytes", 0)
                    for item in request["resources"]
                    if item["disposition"] == "removed"
                ),
            }
            stored_result = dict(result)
            if successor_result is not None:
                stored_result["successor"] = {
                    key: value
                    for key, value in successor_result.items()
                    if key != "prompt"
                }
            connection.execute(
                "INSERT INTO handbacks VALUES(?,?,?,?,?,?)",
                (
                    request["handback_id"],
                    request_hash,
                    request["task_id"],
                    canonical(
                        {
                            "disposition": request["disposition"],
                            "public_metadata": request.get("public_metadata"),
                            "check_results": [item["result"] for item in request["checks"]],
                            "hosted_ci": request["hosted_ci"],
                            "deployment_state": request["deployment_state"],
                            "resource_dispositions": [
                                item["disposition"] for item in request["resources"]
                            ],
                            "successor_task_id": (
                                request["successor_request"]["task_id"]
                                if request["successor_request"]
                                else None
                            ),
                            "blocked_audit_request_id": (
                                f"{request['handback_id']}:blocked-audit"
                            ),
                        }
                    ),
                    canonical(stored_result),
                    request["now"],
                ),
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["handback_id"],
                "CLOSURE_SAGA_STARTED",
                request["disposition"],
                ["BR-CLOSE-001", "BR-RESOURCE-001"],
                before,
                "ARCHIVE_PENDING",
                {
                    "archive_outbox_id": archive_outbox,
                    "successor_task_id": (
                        request["successor_request"]["task_id"]
                        if request["successor_request"]
                        else None
                    ),
                    "blocked_audit_request_id": (
                        f"{request['handback_id']}:blocked-audit"
                    ),
                },
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def takeover_lease(self, raw: Any) -> dict[str, Any]:
        request = validate_takeover(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "takeover-lease")
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (request["task_id"],)
            ).fetchone()
            if not task or task["state"] not in {"RUNNING", "BLOCKED"}:
                fail("TASK_STATE_INVALID", "task is not eligible for lease takeover")
            if (
                task["lease_epoch"] != request["expected_lease_epoch"]
                or task["fencing_token"] != request["expected_fencing_token"]
            ):
                fail("STALE_FENCE", "takeover expectation is stale")
            claim = connection.execute(
                "SELECT expires_at FROM owner_claims WHERE task_id=? AND status='active'",
                (request["task_id"],),
            ).fetchone()
            if not claim or claim["expires_at"] > request["now"]:
                fail(
                    "LEASE_NOT_EXPIRED",
                    "ownership lease is still live",
                    exit_status=EXIT_CONFLICT,
                )
            new_epoch = task["lease_epoch"] + 1
            new_fence = self.next_fence(connection)
            connection.execute(
                "UPDATE tasks SET lease_epoch=?,fencing_token=?,updated_at=? WHERE task_id=?",
                (new_epoch, new_fence, request["now"], request["task_id"]),
            )
            connection.execute(
                """UPDATE owner_claims SET lease_epoch=?,fencing_token=?,
                   heartbeat_at=?,expires_at=? WHERE task_id=? AND status='active'""",
                (
                    new_epoch,
                    new_fence,
                    request["now"],
                    request["lease_expires_at"],
                    request["task_id"],
                ),
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["request_id"],
                "LEASE_TAKEN_OVER",
                "FENCE_ADVANCED",
                ["BR-OWNER-001"],
                task["state"],
                task["state"],
                {"lease_epoch": new_epoch, "fencing_token": new_fence},
            )
            connection.commit()
            return {
                "task_id": request["task_id"],
                "lease_epoch": new_epoch,
                "fencing_token": new_fence,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reconcile_expired_lease(self, raw: Any) -> dict[str, Any]:
        request = validate_expired_lease_reconciliation(raw)
        request_hash = digest(request)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(
                connection, "reconcile-expired-lease"
            )
            # Existing schema-1.3 state directories are upgraded only when this
            # explicit reconciliation is requested. Failed requests roll this
            # DDL back with the rest of the transaction.
            connection.execute(
                """CREATE TABLE IF NOT EXISTS lease_expirations (
                     request_id TEXT PRIMARY KEY,
                     request_hash TEXT NOT NULL,
                     task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
                     result_json TEXT NOT NULL,
                     recorded_at TEXT NOT NULL
                   )"""
            )
            existing = connection.execute(
                """SELECT request_hash,result_json FROM lease_expirations
                   WHERE request_id=?""",
                (request["request_id"],),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "expired-lease request ID was reused",
                        exit_status=EXIT_CONFLICT,
                    )
                replay = json.loads(existing["result_json"])
                task = connection.execute(
                    "SELECT state,fencing_token FROM tasks WHERE task_id=?",
                    (replay["task_id"],),
                ).fetchone()
                claim = connection.execute(
                    "SELECT status FROM owner_claims WHERE claim_id=?",
                    (replay["claim_id"],),
                ).fetchone()
                if (
                    task is None
                    or task["state"] != "EXPIRED"
                    or task["fencing_token"] != replay["tombstone_fencing_token"]
                    or claim is None
                    or claim["status"] != "expired"
                ):
                    fail(
                        "STATE_CORRUPT",
                        "expired-lease tombstone no longer matches authority",
                        exit_status=EXIT_STATE,
                    )
                replay["replayed"] = True
                connection.commit()
                return replay

            prior = connection.execute(
                "SELECT request_id FROM lease_expirations WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            if prior is not None:
                fail(
                    "LEASE_ALREADY_RECONCILED",
                    "task lease was already retired by another request",
                    exit_status=EXIT_CONFLICT,
                    details={"recorded_request_id": prior["request_id"]},
                )

            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (request["task_id"],)
            ).fetchone()
            if task is None or task["state"] not in {"RUNNING", "BLOCKED"}:
                fail(
                    "TASK_STATE_INVALID",
                    "task is not eligible for expired-lease reconciliation",
                    exit_status=EXIT_CONFLICT,
                )
            if (
                task["policy_revision"]
                != request["policy_snapshot_revision"]
                or task["lease_epoch"] != request["expected_lease_epoch"]
                or task["fencing_token"] != request["expected_fencing_token"]
            ):
                fail("STALE_FENCE", "expired-lease expectation is stale")
            if task["external_thread_id"] != request["expected_external_thread_id"]:
                fail(
                    "EXTERNAL_RECEIPT_MISMATCH",
                    "expired-lease external task does not match authority",
                    exit_status=EXIT_CONFLICT,
                )

            claim = connection.execute(
                "SELECT * FROM owner_claims WHERE claim_id=? AND task_id=?",
                (request["expected_owner_claim_id"], request["task_id"]),
            ).fetchone()
            if claim is None or claim["status"] != "active":
                fail("STALE_FENCE", "active ownership claim is missing")
            if (
                claim["lease_epoch"] != request["expected_lease_epoch"]
                or claim["fencing_token"] != request["expected_fencing_token"]
                or claim["expires_at"] != request["expected_lease_expires_at"]
            ):
                fail("STALE_FENCE", "expired-lease claim expectation is stale")

            launch = connection.execute(
                "SELECT receipt_json FROM launches WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            if not launch or not launch["receipt_json"]:
                fail(
                    "EXTERNAL_RECEIPT_REQUIRED",
                    "expired-lease reconciliation requires a canonical launch receipt",
                )
            receipt_external_id = json.loads(launch["receipt_json"])[
                "external_thread_id"
            ]
            if receipt_external_id != request["expected_external_thread_id"]:
                fail(
                    "EXTERNAL_RECEIPT_MISMATCH",
                    "launch receipt external task does not match authority",
                    exit_status=EXIT_CONFLICT,
                )
            if utc_instant(claim["expires_at"]) > utc_instant(request["now"]):
                fail(
                    "LEASE_NOT_EXPIRED",
                    "ownership lease is still live",
                    exit_status=EXIT_CONFLICT,
                )

            tombstone_fence = self.next_fence(connection)
            connection.execute(
                """UPDATE tasks SET state='EXPIRED',fencing_token=?,updated_at=?
                   WHERE task_id=?""",
                (tombstone_fence, request["now"], request["task_id"]),
            )
            connection.execute(
                "UPDATE owner_claims SET status='expired' WHERE claim_id=?",
                (request["expected_owner_claim_id"],),
            )
            connection.execute(
                """UPDATE lifecycle_watchdog
                   SET lifecycle_state='EXPIRED',remaining_work_json=NULL,
                       required_action='NONE',updated_at=?
                   WHERE task_id=?""",
                (request["now"], request["task_id"]),
            )
            result = {
                "task_id": request["task_id"],
                "external_thread_id": request["expected_external_thread_id"],
                "state": "EXPIRED",
                "claim_id": request["expected_owner_claim_id"],
                "claim_status": "expired",
                "lease_expires_at": request["expected_lease_expires_at"],
                "retired_lease_epoch": request["expected_lease_epoch"],
                "retired_fencing_token": request["expected_fencing_token"],
                "tombstone_fencing_token": tombstone_fence,
                "capacity_released": True,
                "closure_created": False,
                "archive_created": False,
                "refill_created": False,
                "required_action": "NONE",
                "replayed": False,
            }
            connection.execute(
                """INSERT INTO lease_expirations(
                     request_id,request_hash,task_id,result_json,recorded_at
                   ) VALUES(?,?,?,?,?)""",
                (
                    request["request_id"],
                    request_hash,
                    request["task_id"],
                    canonical(result),
                    request["now"],
                ),
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["request_id"],
                "LEASE_EXPIRED_RECONCILED",
                "LEASE_EXPIRED",
                ["BR-OWNER-001", "BR-REPORT-001"],
                task["state"],
                "EXPIRED",
                {
                    "claim_id": request["expected_owner_claim_id"],
                    "retired_lease_epoch": request["expected_lease_epoch"],
                    "retired_fencing_token": request["expected_fencing_token"],
                    "tombstone_fencing_token": tombstone_fence,
                    "capacity_released": True,
                    "closure_created": False,
                    "archive_created": False,
                    "refill_created": False,
                },
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reconcile_external_task(self, raw: Any) -> dict[str, Any]:
        request = validate_external_task(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(
                connection, "reconcile-external-task"
            )
            task = connection.execute(
                """SELECT * FROM tasks
                   WHERE source_event_key=? AND outcome_key=?""",
                (
                    request["source_event_key"],
                    request["outcome_key"],
                ),
            ).fetchone()
            if not task:
                fail(
                    "TASK_IDENTITY_MISMATCH",
                    "external task does not match a canonical reservation",
                    exit_status=EXIT_CONFLICT,
                )
            launch = connection.execute(
                "SELECT receipt_json FROM launches WHERE task_id=?",
                (task["task_id"],),
            ).fetchone()
            canonical_external_id = (
                None
                if not launch or not launch["receipt_json"]
                else json.loads(launch["receipt_json"])["external_thread_id"]
            )
            if (
                request["task_id"] == task["task_id"]
                and request["external_thread_id"] == canonical_external_id
            ):
                connection.commit()
                return {
                    "classification": "CANONICAL_RECEIPT_CONFIRMED",
                    "canonical_task_id": task["task_id"],
                    "canonical_external_thread_id": canonical_external_id,
                    "mutation_allowed": True,
                    "capacity_eligible": task["state"]
                    in {"LAUNCH_PENDING", "RUNNING"},
                    "required_actions": [],
                    "zero_change_handback": None,
                }
            self.event(
                connection,
                request["now"],
                task["task_id"],
                request["request_id"],
                "EXTERNAL_MIRROR_STOPPED",
                "MISSING_CANONICAL_RECEIPT",
                ["BR-DUP-001", "BR-LAUNCH-001", "BR-OWNER-001"],
                None,
                "DUPLICATE_STOP",
                {
                    "external_thread_id": request["external_thread_id"],
                    "external_task_id": request["task_id"],
                    "canonical_task_id": task["task_id"],
                    "canonical_external_thread_id": canonical_external_id,
                    "capacity_eligible": False,
                },
            )
            connection.commit()
            return {
                "classification": "DUPLICATE_STOP",
                "canonical_external_thread_id": canonical_external_id,
                "canonical_task_id": task["task_id"],
                "mutation_allowed": False,
                "capacity_eligible": False,
                "required_actions": [
                    "STOP_READ_ONLY",
                    "RETURN_ZERO_CHANGE_HANDBACK",
                    "ARCHIVE_EXTERNAL_MIRROR",
                ],
                "zero_change_handback": {
                    "disposition": "duplicate",
                    "changes": 0,
                    "evidence_refs": [
                        f"external-mirror:{request['request_id']}"
                    ],
                },
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_setup_failure(self, raw: Any) -> dict[str, Any]:
        request = validate_setup_failure(raw)
        request_hash = digest(
            {
                "request_id": request["request_id"],
                "task_id": request["task_id"],
                "policy_snapshot_revision": request["policy_snapshot_revision"],
                "lease_epoch": request["lease_epoch"],
                "fencing_token": request["fencing_token"],
                "reason_code": request["reason_code"],
                "configured_capacity": request["configured_capacity"],
                "runnable_queue_count": request["runnable_queue_count"],
                "empty_outcome": request["empty_outcome"],
                "candidate_task_ids": [
                    candidate["task_id"]
                    for candidate in request["successor_candidates"]
                ],
            }
        )
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "record-setup-failure")
            existing = connection.execute(
                "SELECT * FROM setup_failures WHERE request_id=?",
                (request["request_id"],),
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "setup failure request input changed",
                        exit_status=EXIT_CONFLICT,
                    )
                replay = json.loads(existing["result_json"])
                selected_request = next(
                    (
                        candidate
                        for candidate in request["successor_candidates"]
                        if candidate["task_id"]
                        == existing["selected_successor_task_id"]
                    ),
                    None,
                )
                if replay.get("successor") and selected_request is not None:
                    replay["successor"]["prompt"] = (
                        selected_request["prompt"]
                        + "\n\n<orchestrator_launch_envelope>\n"
                        + canonical(replay["successor"]["envelope"])
                        + "\n</orchestrator_launch_envelope>"
                    )
                connection.commit()
                return replay
            task = self.checked_task(connection, request, {"LAUNCH_PENDING"})
            outbox = connection.execute(
                """SELECT * FROM outbox
                   WHERE task_id=? AND kind='CREATE_THREAD'""",
                (request["task_id"],),
            ).fetchone()
            if not outbox or outbox["state"] != "pending":
                fail(
                    "SETUP_OUTBOX_INVALID",
                    "setup failure requires the current pending create outbox",
                    exit_status=EXIT_CONFLICT,
                )
            saga = connection.execute(
                "SELECT * FROM capacity_sagas WHERE successor_task_id=?",
                (request["task_id"],),
            ).fetchone()
            if saga and saga["configured_capacity"] != request["configured_capacity"]:
                fail(
                    "CAPACITY_CONFIGURATION_MISMATCH",
                    "setup recovery cannot silently change configured capacity",
                    exit_status=EXIT_CONFLICT,
                )
            audit_result = self.recycle_blocked_in_transaction(
                connection,
                audits=request["blocked_audits"],
                now=request["now"],
                request_id=f"{request['request_id']}:blocked-audit",
            )
            connection.execute(
                "UPDATE tasks SET state='FAILED',updated_at=? WHERE task_id=?",
                (request["now"], request["task_id"]),
            )
            connection.execute(
                """UPDATE owner_claims SET status='released',heartbeat_at=?
                   WHERE task_id=? AND status='active'""",
                (request["now"], request["task_id"]),
            )
            connection.execute(
                """UPDATE outbox
                   SET state='poisoned',attempts=attempts+1,updated_at=?
                   WHERE outbox_id=?""",
                (request["now"], outbox["outbox_id"]),
            )
            selected = None
            rejected: list[dict[str, str]] = []
            candidates = sorted(
                request["successor_candidates"],
                key=lambda item: (-item["priority"], item["task_id"]),
            )
            for index, candidate in enumerate(candidates):
                savepoint = f"setup_candidate_{index}"
                connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    selected = self.reserve_launch(
                        connection,
                        candidate,
                        source="setup-failure-successor",
                    )
                    connection.execute(f"RELEASE {savepoint}")
                    break
                except ControlError as error:
                    connection.execute(f"ROLLBACK TO {savepoint}")
                    connection.execute(f"RELEASE {savepoint}")
                    rejected.append(
                        {
                            "task_id": candidate["task_id"],
                            "reason_code": error.code,
                        }
                    )
            selected_task_id = (
                None if selected is None else selected["envelope"]["task_id"]
            )
            active = self.active_or_reserved_count(connection)
            if selected_task_id is not None and active == request["configured_capacity"]:
                outcome = "SUCCESSOR_RESERVED"
            elif request["runnable_queue_count"] == 0:
                if (
                    request["empty_outcome"] == "OWNER_GATED"
                    and not audit_result["owner_gated_task_ids"]
                ):
                    fail(
                        "OWNER_GATE_EVIDENCE_REQUIRED",
                        "OWNER_GATED setup recovery requires a blocked audit",
                        exit_status=EXIT_CONFLICT,
                    )
                outcome = request["empty_outcome"]
            elif active == request["configured_capacity"]:
                outcome = "CAPACITY_FULL"
            else:
                outcome = "CAPACITY_DEFICIT"
            saga_id = (
                saga["saga_id"]
                if saga
                else f"setup-recovery:{request['request_id']}"
            )
            if saga:
                evidence_refs = sorted(
                    set(
                        json.loads(saga["evidence_refs_json"])
                        + request["evidence_refs"]
                    )
                )
                connection.execute(
                    """UPDATE capacity_sagas
                       SET runnable_queue_count=?,outcome=?,
                           successor_task_id=?,successor_receipted=0,
                           evidence_refs_json=?,updated_at=?
                       WHERE saga_id=?""",
                    (
                        request["runnable_queue_count"],
                        outcome,
                        selected_task_id,
                        canonical(evidence_refs),
                        request["now"],
                        saga_id,
                    ),
                )
            else:
                evidence_refs = request["evidence_refs"]
                connection.execute(
                    """INSERT INTO capacity_sagas(
                      saga_id,task_id,configured_capacity,runnable_queue_count,
                      terminal_status,clean_handback,outcome,successor_task_id,
                      successor_receipted,evidence_refs_json,created_at,updated_at
                    ) VALUES(?,?,?,?,?,0,?,?,0,?,?,?)""",
                    (
                        saga_id,
                        request["task_id"],
                        request["configured_capacity"],
                        request["runnable_queue_count"],
                        "setup-failed",
                        outcome,
                        selected_task_id,
                        canonical(evidence_refs),
                        request["now"],
                        request["now"],
                    ),
                )
            capacity_row = connection.execute(
                "SELECT * FROM capacity_sagas WHERE saga_id=?", (saga_id,)
            ).fetchone()
            result = {
                "task_id": request["task_id"],
                "state": "FAILED",
                "failed_outbox_id": outbox["outbox_id"],
                "outbox_state": "poisoned",
                "successor": selected,
                "rejected_candidates": rejected,
                "capacity": self.capacity_result(connection, capacity_row),
            }
            stored_result = dict(result)
            if selected is not None:
                stored_result["successor"] = {
                    key: value for key, value in selected.items() if key != "prompt"
                }
            connection.execute(
                """INSERT INTO setup_failures(
                  request_id,request_hash,task_id,saga_id,failed_outbox_id,
                  selected_successor_task_id,result_json,recorded_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    request["request_id"],
                    request_hash,
                    request["task_id"],
                    saga_id,
                    outbox["outbox_id"],
                    selected_task_id,
                    canonical(stored_result),
                    request["now"],
                ),
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["request_id"],
                "LAUNCH_SETUP_FAILED",
                request["reason_code"],
                ["BR-LAUNCH-001", "BR-CLOSE-001"],
                task["state"],
                "FAILED",
                {
                    "failed_outbox_id": outbox["outbox_id"],
                    "outbox_state": "poisoned",
                    "capacity_eligible": False,
                    "selected_successor_task_id": selected_task_id,
                    "rejected_candidates": rejected,
                },
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                saga_id,
                "CAPACITY_RELEASED",
                outcome,
                ["BR-CLOSE-001", "BR-LAUNCH-001"],
                "LAUNCH_PENDING",
                "FAILED",
                {
                    "configured_capacity": request["configured_capacity"],
                    "runnable_queue_count": request["runnable_queue_count"],
                    "active_or_reserved_count": active,
                    "successor_task_id": selected_task_id,
                },
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def heartbeat(self, raw: Any) -> dict[str, Any]:
        request = validate_heartbeat(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "record-heartbeat")
            task = self.checked_task(connection, request, {"RUNNING", "BLOCKED"})
            canonical_external_id = self.require_external_receipt(
                connection, request
            )
            current_claim = connection.execute(
                """SELECT expires_at FROM owner_claims
                   WHERE task_id=? AND status='active' AND fencing_token=?""",
                (request["task_id"], request["fencing_token"]),
            ).fetchone()
            if (
                current_claim is None
                or utc_instant(current_claim["expires_at"])
                <= utc_instant(request["now"])
            ):
                fail(
                    "LEASE_EXPIRED",
                    "an expired ownership lease cannot be extended",
                    exit_status=EXIT_CONFLICT,
                )
            connection.execute(
                """UPDATE owner_claims SET heartbeat_at=?,expires_at=?
                   WHERE task_id=? AND status='active' AND fencing_token=?""",
                (
                    request["now"],
                    request["lease_expires_at"],
                    request["task_id"],
                    request["fencing_token"],
                ),
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["request_id"],
                "LEASE_HEARTBEAT",
                "CURRENT_FENCE_CONFIRMED",
                ["BR-OWNER-001"],
                task["state"],
                task["state"],
                {
                    "lease_epoch": request["lease_epoch"],
                    "external_thread_id": canonical_external_id,
                },
            )
            connection.commit()
            return {
                "task_id": request["task_id"],
                "state": task["state"],
                "lease_epoch": request["lease_epoch"],
                "lease_expires_at": request["lease_expires_at"],
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def archive_receipt(self, raw: Any) -> dict[str, Any]:
        request = validate_receipt(raw, "archive")
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(
                connection, "record-archive-receipt"
            )
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (request["task_id"],)
            ).fetchone()
            if (
                task
                and task["state"] == "ARCHIVED"
                and request["policy_snapshot_revision"] == task["policy_revision"]
                and request["lease_epoch"] == task["lease_epoch"]
                and request["fencing_token"] == task["fencing_token"]
            ):
                connection.commit()
                return {"task_id": request["task_id"], "state": "ARCHIVED"}
            if not task or task["state"] != "ARCHIVE_PENDING":
                fail("TASK_STATE_INVALID", "task is not awaiting archive")
            if (
                request["policy_snapshot_revision"] != task["policy_revision"]
                or request["lease_epoch"] != task["lease_epoch"]
                or request["fencing_token"] != task["fencing_token"]
            ):
                fail("STALE_FENCE", "archive receipt has stale fencing")
            saga = connection.execute(
                "SELECT * FROM capacity_sagas WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            if not saga:
                fail(
                    "CAPACITY_SAGA_MISSING",
                    "archive is fenced until a durable closure/refill saga exists",
                    exit_status=EXIT_STATE,
                )
            if saga["outcome"] not in {
                "SUCCESSOR_RECEIPTED",
                "EMPTY",
                "OWNER_GATED",
                "CAPACITY_FULL",
            }:
                fail(
                    "CAPACITY_REFILL_PENDING",
                    "archive is fenced until refill is receipted or a terminal empty outcome is evidenced",
                    exit_status=EXIT_CONFLICT,
                    details={"saga_id": saga["saga_id"], "outcome": saga["outcome"]},
                )
            connection.execute(
                "UPDATE tasks SET state='ARCHIVED',updated_at=? WHERE task_id=?",
                (request["now"], request["task_id"]),
            )
            connection.execute(
                "UPDATE outbox SET state='completed',updated_at=? WHERE task_id=? AND kind='ARCHIVE_THREAD'",
                (request["now"], request["task_id"]),
            )
            connection.execute(
                """UPDATE owner_claims SET status='released',heartbeat_at=?
                   WHERE task_id=? AND status='active'""",
                (request["now"], request["task_id"]),
            )
            self.event(
                connection,
                request["now"],
                request["task_id"],
                request["request_id"],
                "ARCHIVE_RECEIPT",
                "EXTERNAL_ARCHIVE_CONFIRMED",
                [],
                "ARCHIVE_PENDING",
                "ARCHIVED",
                {},
            )
            connection.commit()
            return {"task_id": request["task_id"], "state": "ARCHIVED"}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def lifecycle_result(row: sqlite3.Row) -> dict[str, Any]:
        remaining = (
            None
            if row["remaining_work_json"] is None
            else json.loads(row["remaining_work_json"])
        )
        return {
            "task_id": row["task_id"],
            "lifecycle_state": row["lifecycle_state"],
            "worker_status": row["worker_status"],
            "completion_signals": json.loads(row["completion_signals_json"]),
            "evidence_refs": json.loads(row["evidence_refs_json"]),
            "remaining_work": remaining,
            "handback_deadline_checks": row["handback_deadline_checks"],
            "handback_deadline_limit": row["handback_deadline_limit"],
            "required_action": row["required_action"],
            "interrupt_receipt_id": row["interrupt_receipt_id"],
            "status_claim_allowed": row["lifecycle_state"] == "RUNNING",
            "updated_at": row["updated_at"],
        }

    def lifecycle_watchdog(self, raw: Any) -> dict[str, Any]:
        request = validate_lifecycle_watchdog(raw)
        capacity_projection = None
        if request["capacity"] is not None:
            successor = request["capacity"]["successor_request"]
            capacity_projection = {
                "configured_capacity": request["capacity"]["configured_capacity"],
                "runnable_queue_count": request["capacity"][
                    "runnable_queue_count"
                ],
                "empty_outcome": request["capacity"]["empty_outcome"],
                "evidence_refs": request["capacity"]["evidence_refs"],
                "blocked_audits": request["capacity"]["blocked_audits"],
                "successor_request": (
                    None
                    if successor is None
                    else {
                        key: value
                        for key, value in successor.items()
                        if key != "prompt"
                    }
                ),
            }
        # The idempotency key is derived from semantic content only. Volatile
        # wall-clock time ("now") is deliberately excluded so a timestamp-
        # refreshed retry of the same logical request replays cleanly instead
        # of raising IDEMPOTENCY_CONFLICT. Every field that changes the outcome
        # (including remaining_work's observed_at and progress_ref) stays in the
        # digest, so genuine conflicts are still detected. This mirrors the
        # symmetric record_handback path, which also excludes "now".
        request_hash = digest(
            {
                key: request[key]
                for key in (
                    "request_id",
                    "task_id",
                    "policy_snapshot_revision",
                    "lease_epoch",
                    "fencing_token",
                    "external_thread_id",
                    "action",
                    "trigger",
                    "worker_status",
                    "completion_signals",
                    "evidence_refs",
                    "remaining_work",
                    "interrupt_receipt",
                )
            }
            | {"capacity": capacity_projection}
        )
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "lifecycle-watchdog")
            existing_request = connection.execute(
                "SELECT * FROM lifecycle_watchdog_requests WHERE request_id=?",
                (request["request_id"],),
            ).fetchone()
            if existing_request:
                if existing_request["request_hash"] != request_hash:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "lifecycle watchdog request input changed",
                        exit_status=EXIT_CONFLICT,
                    )
                replay = json.loads(existing_request["result_json"])
                # The successor prompt is never persisted (stripped before the
                # result is stored), so re-inject it on replay from the request
                # combined with the authoritative stored envelope. This keeps
                # the interrupt path symmetric with record_handback; the prompt
                # is caller-owned convenience data and never mutates state.
                replay_successor_request = (
                    None
                    if request["capacity"] is None
                    else request["capacity"]["successor_request"]
                )
                if replay.get("successor") and replay_successor_request is not None:
                    replay["successor"]["prompt"] = (
                        replay_successor_request["prompt"]
                        + "\n\n<orchestrator_launch_envelope>\n"
                        + canonical(replay["successor"]["envelope"])
                        + "\n</orchestrator_launch_envelope>"
                    )
                connection.commit()
                return replay
            task = self.checked_task(connection, request, {"RUNNING"})
            self.require_external_receipt(connection, request)
            previous = connection.execute(
                "SELECT * FROM lifecycle_watchdog WHERE task_id=?",
                (request["task_id"],),
            ).fetchone()
            previous_signals = (
                [] if previous is None else json.loads(previous["completion_signals_json"])
            )
            previous_evidence = (
                [] if previous is None else json.loads(previous["evidence_refs_json"])
            )
            signals = sorted(
                set(previous_signals) | set(request["completion_signals"])
            )
            evidence_refs = sorted(
                set(previous_evidence) | set(request["evidence_refs"])
            )
            if request["action"] == "observe":
                remaining = request["remaining_work"]
                fresh_progress = False
                progress_changed = False
                if remaining is not None:
                    age = (
                        utc_instant(request["now"])
                        - utc_instant(remaining["observed_at"])
                    ).total_seconds()
                    fresh_progress = 0 <= age <= REMAINING_WORK_FRESH_SECONDS
                    progress_changed = (
                        previous is None
                        or previous["progress_ref"] != remaining["progress_ref"]
                    )
                completion_candidate = bool(signals) or request[
                    "worker_status"
                ] == "completed"
                prior_state = (
                    "RUNNING" if previous is None else previous["lifecycle_state"]
                )
                if (
                    prior_state == "INTERRUPT_REQUIRED"
                    and fresh_progress
                    and progress_changed
                ):
                    lifecycle_state = "COMPLETION_CANDIDATE"
                    deadline_checks = 0
                    required_action = "REQUEST_HANDBACK"
                elif prior_state == "INTERRUPT_REQUIRED":
                    lifecycle_state = "INTERRUPT_REQUIRED"
                    deadline_checks = previous["handback_deadline_checks"]
                    required_action = "TERMINALIZE"
                elif not completion_candidate:
                    lifecycle_state = "RUNNING"
                    deadline_checks = 0
                    required_action = "CONTINUE"
                else:
                    lifecycle_state = "COMPLETION_CANDIDATE"
                    if fresh_progress and progress_changed:
                        deadline_checks = 0
                    elif prior_state != "COMPLETION_CANDIDATE":
                        deadline_checks = 0
                    else:
                        deadline_checks = (
                            previous["handback_deadline_checks"] + 1
                        )
                    if deadline_checks >= HANDBACK_DEADLINE_CHECKS:
                        lifecycle_state = "INTERRUPT_REQUIRED"
                        required_action = "TERMINALIZE"
                    else:
                        required_action = "REQUEST_HANDBACK"
                remaining_json = None if remaining is None else canonical(remaining)
                progress_ref = None if remaining is None else remaining["progress_ref"]
                progress_observed_at = (
                    None if remaining is None else remaining["observed_at"]
                )
                connection.execute(
                    """INSERT INTO lifecycle_watchdog(
                      task_id,lifecycle_state,worker_status,
                      completion_signals_json,evidence_refs_json,
                      remaining_work_json,progress_ref,progress_observed_at,
                      handback_deadline_checks,handback_deadline_limit,
                      required_action,interrupt_receipt_id,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,?)
                    ON CONFLICT(task_id) DO UPDATE SET
                      lifecycle_state=excluded.lifecycle_state,
                      worker_status=excluded.worker_status,
                      completion_signals_json=excluded.completion_signals_json,
                      evidence_refs_json=excluded.evidence_refs_json,
                      remaining_work_json=excluded.remaining_work_json,
                      progress_ref=excluded.progress_ref,
                      progress_observed_at=excluded.progress_observed_at,
                      handback_deadline_checks=excluded.handback_deadline_checks,
                      handback_deadline_limit=excluded.handback_deadline_limit,
                      required_action=excluded.required_action,
                      updated_at=excluded.updated_at""",
                    (
                        request["task_id"],
                        lifecycle_state,
                        request["worker_status"],
                        canonical(signals),
                        canonical(evidence_refs),
                        remaining_json,
                        progress_ref,
                        progress_observed_at,
                        deadline_checks,
                        HANDBACK_DEADLINE_CHECKS,
                        required_action,
                        request["now"],
                    ),
                )
                self.event(
                    connection,
                    request["now"],
                    request["task_id"],
                    request["request_id"],
                    "LIFECYCLE_RECONCILED",
                    required_action,
                    ["BR-CLOSE-001", "BR-LAUNCH-001"],
                    prior_state,
                    lifecycle_state,
                    {
                        "trigger": request["trigger"],
                        "worker_status": request["worker_status"],
                        "completion_signal_count": len(signals),
                        "fresh_progress": fresh_progress and progress_changed,
                        "handback_deadline_checks": deadline_checks,
                        "handback_deadline_limit": HANDBACK_DEADLINE_CHECKS,
                    },
                )
                updated = connection.execute(
                    "SELECT * FROM lifecycle_watchdog WHERE task_id=?",
                    (request["task_id"],),
                ).fetchone()
                result = {
                    "lifecycle": self.lifecycle_result(updated),
                    "successor": None,
                    "capacity": None,
                }
            else:
                if previous is None or previous["lifecycle_state"] != "INTERRUPT_REQUIRED":
                    fail(
                        "INTERRUPT_NOT_REQUIRED",
                        "interrupt receipt requires a watchdog terminalize decision",
                        exit_status=EXIT_CONFLICT,
                    )
                receipt_id = request["interrupt_receipt"]["receipt_id"]
                if previous["interrupt_receipt_id"] is not None:
                    fail(
                        "INTERRUPT_RECEIPT_CONFLICT",
                        "task already has an interrupt receipt",
                        exit_status=EXIT_CONFLICT,
                    )
                capacity = request["capacity"]
                connection.execute(
                    """UPDATE owner_claims SET status='released',heartbeat_at=?
                       WHERE task_id=? AND status='active'""",
                    (request["now"], request["task_id"]),
                )
                audit_result = self.recycle_blocked_in_transaction(
                    connection,
                    audits=capacity["blocked_audits"],
                    now=request["now"],
                    request_id=f"{receipt_id}:blocked-audit",
                )
                successor_result = None
                successor_request = capacity["successor_request"]
                resumed_task_id = audit_result["selected_task_id"]
                if resumed_task_id is not None and successor_request is not None:
                    fail(
                        "REFILL_EVIDENCE_CONFLICT",
                        "a resumed blocked task and a new successor cannot fill the same slot",
                        exit_status=EXIT_CONFLICT,
                    )
                if successor_request is not None:
                    successor_result = self.reserve_launch(
                        connection,
                        successor_request,
                        source="lifecycle-watchdog-successor",
                    )
                if (
                    capacity["runnable_queue_count"] > 0
                    and resumed_task_id is None
                    and successor_request is None
                ):
                    fail(
                        "REFILL_PROOF_REQUIRED",
                        "interrupt receipt requires an exact successor while runnable work exists",
                        exit_status=EXIT_CONFLICT,
                    )
                if (
                    capacity["runnable_queue_count"] == 0
                    and successor_request is not None
                ):
                    fail(
                        "CAPACITY_EVIDENCE_CONFLICT",
                        "zero runnable work cannot carry a successor reservation",
                        exit_status=EXIT_CONFLICT,
                    )
                if (
                    capacity["empty_outcome"] == "OWNER_GATED"
                    and not audit_result["owner_gated_task_ids"]
                ):
                    fail(
                        "OWNER_GATE_EVIDENCE_REQUIRED",
                        "OWNER_GATED interrupt outcome requires a blocked audit",
                        exit_status=EXIT_CONFLICT,
                    )
                active = self.active_or_reserved_count(connection)
                if (
                    capacity["runnable_queue_count"] > 0
                    and active != capacity["configured_capacity"]
                ):
                    fail(
                        "REFILL_PROOF_REQUIRED",
                        "interrupt receipt cannot release capacity without exact refill proof",
                        exit_status=EXIT_CONFLICT,
                        details={
                            "configured_capacity": capacity[
                                "configured_capacity"
                            ],
                            "active_or_reserved_count": active,
                        },
                    )
                if successor_request is not None:
                    capacity_outcome = "SUCCESSOR_RESERVED"
                elif resumed_task_id is not None:
                    capacity_outcome = "CAPACITY_FULL"
                elif capacity["runnable_queue_count"] == 0:
                    capacity_outcome = capacity["empty_outcome"]
                else:
                    capacity_outcome = "CAPACITY_FULL"
                saga_id = f"interrupt:{receipt_id}"
                closure = {
                    "disposition": "interrupted/notLoaded",
                    "interrupt_receipt_id": receipt_id,
                    "completion_signals": signals,
                    "evidence_refs": evidence_refs,
                    "worker_status": "interrupted",
                }
                connection.execute(
                    """UPDATE tasks SET state='ARCHIVE_PENDING',
                       closure_json=?,updated_at=? WHERE task_id=?""",
                    (canonical(closure), request["now"], request["task_id"]),
                )
                connection.execute(
                    """INSERT INTO capacity_sagas(
                      saga_id,task_id,configured_capacity,runnable_queue_count,
                      terminal_status,clean_handback,outcome,successor_task_id,
                      successor_receipted,evidence_refs_json,created_at,updated_at
                    ) VALUES(?,?,?,?,? ,0,?,?,0,?,?,?)""",
                    (
                        saga_id,
                        request["task_id"],
                        capacity["configured_capacity"],
                        capacity["runnable_queue_count"],
                        "interrupted/notLoaded",
                        capacity_outcome,
                        (
                            None
                            if successor_request is None
                            else successor_request["task_id"]
                        ),
                        canonical(capacity["evidence_refs"]),
                        request["now"],
                        request["now"],
                    ),
                )
                archive_outbox = f"archive:{request['task_id']}"
                connection.execute(
                    """INSERT OR IGNORE INTO outbox(
                      outbox_id,kind,idempotency_key,task_id,payload_json,state,
                      attempts,created_at,updated_at
                    ) VALUES(?, 'ARCHIVE_THREAD', ?, ?, ?, 'pending', 0, ?, ?)""",
                    (
                        archive_outbox,
                        archive_outbox,
                        request["task_id"],
                        canonical(
                            {
                                "task_id": request["task_id"],
                                "external_thread_id": task["external_thread_id"],
                            }
                        ),
                        request["now"],
                        request["now"],
                    ),
                )
                connection.execute(
                    """UPDATE lifecycle_watchdog SET
                       lifecycle_state='INTERRUPTED',worker_status='interrupted',
                       required_action='ARCHIVE',interrupt_receipt_id=?,
                       updated_at=? WHERE task_id=?""",
                    (receipt_id, request["now"], request["task_id"]),
                )
                self.event(
                    connection,
                    request["now"],
                    request["task_id"],
                    request["request_id"],
                    "LIFECYCLE_INTERRUPT_RECEIPTED",
                    capacity_outcome,
                    ["BR-CLOSE-001", "BR-LAUNCH-001"],
                    "INTERRUPT_REQUIRED",
                    "INTERRUPTED",
                    {
                        "configured_capacity": capacity[
                            "configured_capacity"
                        ],
                        "runnable_queue_count": capacity[
                            "runnable_queue_count"
                        ],
                        "active_or_reserved_count": active,
                        "successor_task_id": (
                            None
                            if successor_request is None
                            else successor_request["task_id"]
                        ),
                    },
                )
                updated = connection.execute(
                    "SELECT * FROM lifecycle_watchdog WHERE task_id=?",
                    (request["task_id"],),
                ).fetchone()
                capacity_row = connection.execute(
                    "SELECT * FROM capacity_sagas WHERE saga_id=?",
                    (saga_id,),
                ).fetchone()
                result = {
                    "lifecycle": self.lifecycle_result(updated),
                    "successor": successor_result,
                    "capacity": self.capacity_result(connection, capacity_row),
                }
            stored_result = dict(result)
            if stored_result["successor"] is not None:
                stored_result["successor"] = {
                    key: value
                    for key, value in stored_result["successor"].items()
                    if key != "prompt"
                }
            connection.execute(
                """INSERT INTO lifecycle_watchdog_requests(
                  request_id,request_hash,task_id,result_json,recorded_at
                ) VALUES(?,?,?,?,?)""",
                (
                    request["request_id"],
                    request_hash,
                    request["task_id"],
                    canonical(stored_result),
                    request["now"],
                ),
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def capacity_watchdog(self, raw: Any) -> dict[str, Any]:
        request = validate_capacity_watchdog(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "capacity-watchdog")
            row = connection.execute(
                "SELECT * FROM capacity_sagas WHERE saga_id=?",
                (request["saga_id"],),
            ).fetchone()
            if not row:
                fail("CAPACITY_SAGA_MISSING", "capacity saga does not exist")
            if request["configured_capacity"] != row["configured_capacity"]:
                fail(
                    "CAPACITY_CONFIGURATION_MISMATCH",
                    "watchdog cannot silently change configured capacity",
                    exit_status=EXIT_CONFLICT,
                )
            audit_result = self.recycle_blocked_in_transaction(
                connection,
                audits=request["blocked_audits"],
                now=request["now"],
                request_id=f"{request['request_id']}:blocked-audit",
            )
            successor_result = None
            successor_task_id = row["successor_task_id"]
            if request["successor_request"] is not None:
                candidate = request["successor_request"]
                if successor_task_id and candidate["task_id"] != successor_task_id:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "capacity saga already selected another successor",
                        exit_status=EXIT_CONFLICT,
                    )
                if not successor_task_id:
                    successor_result = self.reserve_launch(
                        connection, candidate, source="capacity-watchdog"
                    )
                    successor_task_id = candidate["task_id"]
            active = self.active_or_reserved_count(connection)
            receipted = bool(row["successor_receipted"])
            if successor_task_id:
                successor = connection.execute(
                    """SELECT task.state FROM tasks AS task
                       JOIN owner_claims AS claim ON claim.task_id=task.task_id
                       WHERE task.task_id=? AND claim.status='active'""",
                    (successor_task_id,),
                ).fetchone()
                successor_state = (
                    None if successor is None else successor["state"]
                )
                if receipted and successor_state == "RUNNING":
                    outcome = "SUCCESSOR_RECEIPTED"
                elif (
                    not receipted
                    and successor_state in {"LAUNCH_PENDING", "RUNNING"}
                ):
                    outcome = "SUCCESSOR_RESERVED"
                else:
                    outcome = "CAPACITY_DEFICIT"
            elif request["runnable_queue_count"] == 0:
                if (
                    request["empty_outcome"] == "OWNER_GATED"
                    and not audit_result["owner_gated_task_ids"]
                ):
                    fail(
                        "OWNER_GATE_EVIDENCE_REQUIRED",
                        "OWNER_GATED watchdog outcome requires a blocked audit",
                        exit_status=EXIT_CONFLICT,
                    )
                outcome = request["empty_outcome"]
            elif active == row["configured_capacity"]:
                outcome = "CAPACITY_FULL"
            else:
                outcome = "CAPACITY_DEFICIT"
            evidence_refs = sorted(
                set(json.loads(row["evidence_refs_json"]) + request["evidence_refs"])
            )
            connection.execute(
                """UPDATE capacity_sagas
                   SET runnable_queue_count=?,outcome=?,successor_task_id=?,
                       evidence_refs_json=?,updated_at=?
                   WHERE saga_id=?""",
                (
                    request["runnable_queue_count"],
                    outcome,
                    successor_task_id,
                    canonical(evidence_refs),
                    request["now"],
                    request["saga_id"],
                ),
            )
            self.event(
                connection,
                request["now"],
                row["task_id"],
                request["request_id"],
                "CAPACITY_WATCHDOG_RECONCILED",
                outcome,
                ["BR-CLOSE-001", "BR-LAUNCH-001"],
                None,
                None,
                {
                    "saga_id": request["saga_id"],
                    "configured_capacity": row["configured_capacity"],
                    "runnable_queue_count": request["runnable_queue_count"],
                    "active_or_reserved_count": active,
                    "successor_task_id": successor_task_id,
                },
            )
            updated = connection.execute(
                "SELECT * FROM capacity_sagas WHERE saga_id=?",
                (request["saga_id"],),
            ).fetchone()
            connection.commit()
            return {
                "capacity": self.capacity_result(connection, updated),
                "successor": successor_result,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def recycle_blocked_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        audits: list[dict[str, Any]],
        now: str,
        request_id: str,
    ) -> dict[str, Any]:
        blocked = connection.execute(
            "SELECT * FROM tasks WHERE state='BLOCKED' ORDER BY task_id"
        ).fetchall()
        expected = {row["task_id"] for row in blocked}
        provided = {item["task_id"] for item in audits}
        if expected != provided:
            fail(
                "BLOCKED_AUDIT_INCOMPLETE",
                "all blocked tasks must be reconciled in one transaction",
                details={
                    "missing": sorted(expected - provided),
                    "unknown": sorted(provided - expected),
                },
            )
        rows = {row["task_id"]: row for row in blocked}
        resumable = []
        archived = []
        owner_gated = []
        for audit in audits:
            row = rows[audit["task_id"]]
            block = {
                **audit,
                "audit_required": False,
                "audited_at": now,
            }
            if audit["outcome"] == "resume":
                fanout = len(json.loads(row["dependencies_json"]))
                resumable.append((row, fanout, block))
            elif audit["outcome"] == "archive":
                connection.execute(
                    "UPDATE tasks SET state='ARCHIVED',block_json=?,updated_at=? WHERE task_id=?",
                    (canonical(block), now, row["task_id"]),
                )
                connection.execute(
                    "UPDATE owner_claims SET status='released' WHERE task_id=?",
                    (row["task_id"],),
                )
                archived.append(row["task_id"])
            elif audit["outcome"] == "owner_gate":
                connection.execute(
                    "UPDATE tasks SET block_json=?,updated_at=? WHERE task_id=?",
                    (canonical(block), now, row["task_id"]),
                )
                owner_gated.append(row["task_id"])
            else:
                connection.execute(
                    "UPDATE tasks SET block_json=?,updated_at=? WHERE task_id=?",
                    (canonical(block), now, row["task_id"]),
                )
        resumable.sort(
            key=lambda item: (
                -item[0]["priority"],
                -item[1],
                item[0]["created_at"],
                item[0]["task_id"],
            )
        )
        ranked = []
        for index, (row, fanout, block) in enumerate(resumable):
            ranked.append(
                {
                    "rank": index + 1,
                    "task_id": row["task_id"],
                    "priority": row["priority"],
                    "dependency_fanout": fanout,
                    "reason_code": block["classification"],
                }
            )
            if index == 0:
                connection.execute(
                    "UPDATE tasks SET state='RUNNING',block_json=NULL,updated_at=? WHERE task_id=?",
                    (now, row["task_id"]),
                )
            else:
                connection.execute(
                    "UPDATE tasks SET block_json=?,updated_at=? WHERE task_id=?",
                    (canonical(block), now, row["task_id"]),
                )
        self.event(
            connection,
            now,
            None,
            request_id,
            "BLOCKED_QUEUE_RECYCLED",
            "AUDIT_COMMITTED",
            ["BR-BLOCK-001", "BR-CI-001"],
            "BLOCKED",
            "RUNNING" if ranked else "BLOCKED",
            {"ranked_task_ids": [item["task_id"] for item in ranked]},
        )
        return {
            "ranked_resumable": ranked,
            "selected_task_id": ranked[0]["task_id"] if ranked else None,
            "archived_task_ids": sorted(archived),
            "owner_gated_task_ids": sorted(owner_gated),
        }

    def recycle(self, raw: Any) -> dict[str, Any]:
        request = validate_recycle(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "recycle-queue")
            result = self.recycle_blocked_in_transaction(
                connection,
                audits=request["audits"],
                now=request["now"],
                request_id=request["request_id"],
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self, raw: Any) -> dict[str, Any]:
        request = validate_migration(raw)
        path = Path(request["input_path"])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            fail("INPUT_UNSAFE", "legacy input must be a bounded regular file")
        original = path.read_bytes()
        try:
            legacy = json.loads(original, object_pairs_hook=pairs_without_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError):
            fail("LEGACY_INCOMPATIBLE", "legacy input is not valid UTF-8 JSON")
        if not isinstance(legacy, dict) or not {"generated", "items"} <= set(legacy):
            fail(
                "LEGACY_INCOMPATIBLE",
                "legacy board must contain generated and items",
            )
        if not isinstance(legacy["items"], list):
            fail("LEGACY_INCOMPATIBLE", "legacy items must be a list")
        warnings = []
        top_level_extras = sorted(
            set(legacy) - {"generated", "items", "note", "_comment"}
        )
        if top_level_extras:
            warnings.append(
                {
                    "code": "PRESERVED_UNKNOWN_TOP_LEVEL_FIELDS",
                    "fields": top_level_extras,
                }
            )
        decoded = original.decode("utf-8")
        if any(pattern.search(decoded) for pattern in SECRET_PATTERNS):
            warnings.append({"code": "SENSITIVE_SOURCE_QUARANTINED"})
        provisional = []
        known_categories = {"act", "decide", "done", "plan", "play", "review"}
        for index, item in enumerate(legacy["items"]):
            if not isinstance(item, dict):
                fail("LEGACY_INCOMPATIBLE", "legacy item must be an object")
            category = item.get("cat")
            if category not in known_categories:
                warnings.append({"index": index, "code": "UNKNOWN_CATEGORY"})
                category = "review"
            extras = sorted(set(item) - {"autoflip", "cat", "context", "id", "link", "project", "rec", "status", "title"})
            if extras:
                warnings.append({"index": index, "code": "PRESERVED_UNKNOWN_FIELDS", "fields": extras})
            warnings.append({"index": index, "code": "MISSING_TYPED_OWNER_DEPENDENCIES_REVISION"})
            provisional.append(
                {
                    "legacy_ref": f"legacy-item-{index}",
                    "category": category,
                    "provisional_state": {
                        "act": "candidate_running",
                        "decide": "needs_classification",
                        "done": "historical_closed",
                        "plan": "queued",
                        "play": "showcase_non_work",
                        "review": "review",
                    }[category],
                }
            )
        result = {
            "dry_run": request["dry_run"],
            "source_ref": request["request_id"],
            "item_count": len(provisional),
            "warnings": warnings,
            "provisional": provisional,
        }
        if request["dry_run"]:
            return result
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(connection, "migrate-decisions")
            connection.execute(
                "INSERT OR IGNORE INTO legacy_blobs VALUES(?,?,?,?)",
                (
                    request["request_id"],
                    original,
                    canonical(warnings),
                    request["now"],
                ),
            )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "LEGACY_IMPORTED_QUARANTINED",
                "DISPLAY_DATA_NOT_AUTHORITY",
                ["BR-PRIVACY-001", "BR-BLOCK-001"],
                None,
                None,
                {"source_ref": request["request_id"], "item_count": len(provisional)},
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def status(self, now: str | None = None) -> dict[str, Any]:
        if now is not None:
            timestamp(now)
        connection = self.connect()
        try:
            tasks = []
            for row in connection.execute(
                "SELECT * FROM tasks ORDER BY priority DESC,created_at,task_id"
            ):
                target = json.loads(row["target_json"])
                raw_block = (
                    None
                    if row["block_json"] is None
                    else json.loads(row["block_json"])
                )
                block = (
                    None
                    if raw_block is None
                    else {
                        key: raw_block[key]
                        for key in (
                            "classification",
                            "reason_code",
                            "audit_required",
                            "blocked_at",
                            "audited_at",
                        )
                        if key in raw_block
                    }
                )
                timing = connection.execute(
                    "SELECT * FROM task_timing WHERE task_id=?",
                    (row["task_id"],),
                ).fetchone()
                lifecycle = connection.execute(
                    "SELECT * FROM lifecycle_watchdog WHERE task_id=?",
                    (row["task_id"],),
                ).fetchone()
                claim = connection.execute(
                    """SELECT status,expires_at FROM owner_claims
                       WHERE task_id=? ORDER BY acquired_at DESC LIMIT 1""",
                    (row["task_id"],),
                ).fetchone()
                stale = (
                    None
                    if now is None
                    or claim is None
                    or claim["status"] not in {"active", "expired"}
                    else utc_instant(claim["expires_at"]) <= utc_instant(now)
                )
                tasks.append(
                    {
                        "task_id": row["task_id"],
                        "state": row["state"],
                        "priority": row["priority"],
                        "repo_alias": target["remote"].split("/", 1)[1],
                        "path": target["path"],
                        "canonical_external_thread_id": row[
                            "external_thread_id"
                        ],
                        "capacity_eligible": row["state"]
                        in {"LAUNCH_PENDING", "RUNNING"},
                        "updated_at": row["updated_at"],
                        "block": block,
                        "duration": (
                            None if timing is None else self.duration_result(timing)
                        ),
                        "lifecycle": (
                            None
                            if lifecycle is None
                            else self.lifecycle_result(lifecycle)
                        ),
                        "freshness": {
                            "evaluated_at": now,
                            "lease_expires_at": (
                                None if claim is None else claim["expires_at"]
                            ),
                            "stale": stale,
                            "state": (
                                "EXPIRED"
                                if row["state"] == "EXPIRED"
                                and claim is not None
                                and claim["status"] == "expired"
                                else (
                                    "UNKNOWN_CLOCK"
                                    if now is None
                                    else (
                                        "NO_ACTIVE_CLAIM"
                                        if claim is None
                                        or claim["status"] != "active"
                                        else ("STALE" if stale else "FRESH")
                                    )
                                )
                            ),
                        },
                    }
                )
            rules = [
                {
                    "id": rule["id"],
                    "revision": rule["rule_revision"],
                    "state": rule["state"],
                    "directive": rule["directive"],
                    "provenance": {
                        key: rule["provenance"][key]
                        for key in (
                            "source_kind",
                            "recorded_at",
                            "redacted_summary",
                        )
                    },
                }
                for rule in self.rules(connection)
            ]
            capacity = [
                self.capacity_result(connection, row)
                for row in connection.execute(
                    "SELECT * FROM capacity_sagas ORDER BY created_at,saga_id"
                )
            ]
            active_lane_counts = {
                bucket: connection.execute(
                    """SELECT count(*) FROM task_timing AS timing
                       JOIN tasks AS task ON task.task_id=timing.task_id
                       WHERE timing.current_lane=?
                         AND task.state='RUNNING'""",
                    (bucket,),
                ).fetchone()[0]
                for bucket in DURATION_BUCKETS
            }
            reserved_setup_lane_counts = {
                bucket: connection.execute(
                    """SELECT count(*) FROM task_timing AS timing
                       JOIN tasks AS task ON task.task_id=timing.task_id
                       WHERE timing.current_lane=?
                         AND task.state='LAUNCH_PENDING'""",
                    (bucket,),
                ).fetchone()[0]
                for bucket in DURATION_BUCKETS
            }
            calibration_groups = [
                {
                    "task_family": row["task_family"],
                    "tool_family": row["tool_family"],
                    "environment_class": row["environment_class"],
                    "completed_sample_count": row["sample_count"],
                    "automatic_prior_eligible": row["sample_count"]
                    >= MIN_CALIBRATION_SAMPLES,
                }
                for row in connection.execute(
                    """SELECT task_family,tool_family,environment_class,
                              count(*) AS sample_count
                       FROM duration_samples
                       GROUP BY task_family,tool_family,environment_class
                       ORDER BY task_family,tool_family,environment_class"""
                )
            ]
            lifecycle_reconciliation_required = sorted(
                item["task_id"]
                for item in tasks
                if item["state"] == "RUNNING"
                and (
                    item["lifecycle"] is None
                    or not item["lifecycle"]["status_claim_allowed"]
                )
            )
            adoption_row = connection.execute(
                """SELECT request_id,body_json,result_json,recorded_at
                   FROM dispatcher_adoptions
                   ORDER BY recorded_at DESC,request_id DESC LIMIT 1"""
            ).fetchone()
            adoption = None
            if adoption_row is not None:
                adoption_body = json.loads(adoption_row["body_json"])
                adoption_result = json.loads(adoption_row["result_json"])
                adoption = {
                    "request_id": adoption_row["request_id"],
                    "adoption_mode": adoption_body["adoption_mode"],
                    "plugin_version": adoption_body["plugin_version"],
                    "recorded_at": adoption_row["recorded_at"],
                    "proofs": adoption_body["proofs"],
                    "covered_path_dispatcher_enforcement": adoption_result[
                        "covered_path_dispatcher_enforcement"
                    ],
                    "universal_dispatcher_enforcement": adoption_result[
                        "universal_dispatcher_enforcement"
                    ],
                }
            authority = self.authority(connection)
            federation_members = [
                {
                    "authority_id": row["authority_id"],
                    "configured_capacity": row["configured_capacity"],
                    "source_state_revision": row["source_state_revision"],
                    "state": row["state"],
                    "updated_at": row["updated_at"],
                }
                for row in connection.execute(
                    """SELECT authority_id,configured_capacity,
                              source_state_revision,state,updated_at
                       FROM federation_members ORDER BY authority_id"""
                )
            ]
            authority["federation_members"] = federation_members
            authority["federated_configured_capacity"] = sum(
                item["configured_capacity"] for item in federation_members
            )
            authority["local_worker_launch_allowed"] = authority["state"] in {
                "ACTIVE_ROOT",
                "SUBORDINATE",
            }
            authority["requires_subordinate_shard"] = (
                authority["state"] == "ACTIVE_FEDERATION_ROOT"
            )
            authority["transfer_steps"] = (
                []
                if authority["active_transfer_id"] is None
                else [
                    {
                        "step": row["step"],
                        "receipt": json.loads(row["result_json"]),
                        "recorded_at": row["recorded_at"],
                    }
                    for row in connection.execute(
                        """SELECT step,result_json,recorded_at
                           FROM authority_transfer_steps
                           WHERE transfer_id=? ORDER BY recorded_at,step""",
                        (authority["active_transfer_id"],),
                    )
                ]
            )
            return {
                "schema_version": self.metadata(connection, "schema_version"),
                "revision": int(self.metadata(connection, "revision")),
                "policy_revision": int(self.metadata(connection, "policy_revision")),
                "authority": authority,
                "worker_capacity": {
                    "configured_capacity": int(
                        self.metadata(connection, "configured_capacity")
                    ),
                    "active_or_reserved_count": self.active_or_reserved_count(
                        connection
                    ),
                    "root_excluded": True,
                },
                "tasks": tasks,
                "rules": rules,
                "capacity": capacity,
                "capacity_failure": any(
                    item["failure_state"] is not None for item in capacity
                ),
                "duration": {
                    "bucket_order": list(DURATION_BUCKETS),
                    "non_runtime_states": sorted(NON_RUNTIME_STATES),
                    "root_excluded_from_worker_capacity": True,
                    "receipt_backed_lane_counts": active_lane_counts,
                    "reserved_setup_lane_counts": reserved_setup_lane_counts,
                    "freshness": {
                        "evaluated_at": now,
                        "stale_task_count": (
                            None
                            if now is None
                            else sum(
                                item["freshness"]["stale"] is True
                                for item in tasks
                            )
                        ),
                        "state": "UNKNOWN_CLOCK" if now is None else "EVALUATED",
                    },
                    "calibration_groups": calibration_groups,
                    "minimum_completed_samples": MIN_CALIBRATION_SAMPLES,
                },
                "lifecycle_watchdog": {
                    "deadline_checks_default": HANDBACK_DEADLINE_CHECKS,
                    "remaining_work_fresh_seconds": REMAINING_WORK_FRESH_SECONDS,
                    "reconcile_after": [
                        "worker-message",
                        "wait-timeout",
                        "before-status-claim",
                    ],
                    "reconciliation_required_task_ids": (
                        lifecycle_reconciliation_required
                    ),
                    "status_claim_allowed": not lifecycle_reconciliation_required,
                    "root_is_not_worker": True,
                    "platform_dispatcher_enforcement": False,
                    "covered_path_dispatcher_enforcement": bool(
                        adoption
                        and adoption["covered_path_dispatcher_enforcement"]
                    ),
                    "dispatcher_adoption": adoption,
                },
                "outbox": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT outbox_id,kind,task_id,state,attempts,created_at,updated_at FROM outbox ORDER BY created_at,outbox_id"
                    )
                ],
            }
        finally:
            connection.close()

    def record_dispatcher_adoption(self, raw: Any) -> dict[str, Any]:
        request = validate_dispatcher_adoption(raw)
        request_hash = digest(request)
        result = {
            "request_id": request["request_id"],
            "adoption_mode": request["adoption_mode"],
            "plugin_version": request["plugin_version"],
            "covered_path_dispatcher_enforcement": True,
            "universal_dispatcher_enforcement": False,
            "recorded_at": request["now"],
            "replayed": False,
        }
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.require_operational_authority(
                connection, "record-dispatcher-adoption"
            )
            existing = connection.execute(
                """SELECT request_hash,result_json FROM dispatcher_adoptions
                   WHERE request_id=?""",
                (request["request_id"],),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    fail(
                        "IDEMPOTENCY_CONFLICT",
                        "dispatcher adoption request ID was reused",
                        exit_status=EXIT_CONFLICT,
                    )
                replay = json.loads(existing["result_json"])
                replay["replayed"] = True
                connection.commit()
                return replay
            connection.execute(
                """INSERT INTO dispatcher_adoptions(
                     request_id,request_hash,body_json,result_json,recorded_at
                   ) VALUES(?,?,?,?,?)""",
                (
                    request["request_id"],
                    request_hash,
                    canonical(request),
                    canonical(result),
                    request["now"],
                ),
            )
            self.bump_revision(connection)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def effective_rules(self, raw: Any) -> dict[str, Any]:
        request = validate_effective_rules(raw)
        connection = self.connect()
        try:
            included, excluded = resolve_rules(
                self.rules(connection), request["context"], request["now"]
            )
            return {
                "policy_snapshot_revision": int(
                    self.metadata(connection, "policy_revision")
                ),
                "context": request["context"],
                "included": [
                    {
                        "rule_id": rule["id"],
                        "revision": rule["rule_revision"],
                        "effect": rule["effect"],
                        "directive": rule["directive"],
                        "why": rule["why"],
                    }
                    for rule in included
                ],
                "excluded": excluded,
            }
        finally:
            connection.close()


AUTHORITY_RECEIPT_PHASES = {
    "SOURCE_PREPARED",
    "TARGET_STAGED",
    "SOURCE_FINALIZED",
    "TARGET_ACTIVE",
    "SUBORDINATE_ACTIVE",
    "ABORTED",
}


def validate_authority_receipt(value: Any, label: str) -> dict[str, Any]:
    receipt = strict(
        value,
        {
            "transfer_id",
            "phase",
            "subject_authority_id",
            "target_authority_id",
            "authority_epoch",
            "state_revision",
            "configured_capacity",
            "member_authority_ids",
            "membership_digest",
            "recorded_at",
            "receipt_sha256",
            "replayed",
        },
        label=label,
    )
    members = receipt["member_authority_ids"]
    if not isinstance(members, list) or len(members) > 16:
        fail("SCHEMA_INVALID", f"{label}.member_authority_ids is invalid")
    normalized_members = [
        identifier(item, f"{label}.member_authority_ids[]") for item in members
    ]
    if normalized_members != sorted(set(normalized_members)):
        fail(
            "SCHEMA_INVALID",
            f"{label}.member_authority_ids must be sorted and unique",
        )
    normalized = {
        "transfer_id": identifier(receipt["transfer_id"], f"{label}.transfer_id"),
        "phase": enum(receipt["phase"], f"{label}.phase", AUTHORITY_RECEIPT_PHASES),
        "subject_authority_id": identifier(
            receipt["subject_authority_id"], f"{label}.subject_authority_id"
        ),
        "target_authority_id": identifier(
            receipt["target_authority_id"], f"{label}.target_authority_id"
        ),
        "authority_epoch": bounded_int(
            receipt["authority_epoch"], f"{label}.authority_epoch", 1, 2_147_483_647
        ),
        "state_revision": bounded_int(
            receipt["state_revision"], f"{label}.state_revision", 0, 2_147_483_647
        ),
        "configured_capacity": bounded_int(
            receipt["configured_capacity"],
            f"{label}.configured_capacity",
            1,
            1024,
        ),
        "member_authority_ids": normalized_members,
        "membership_digest": text(
            receipt["membership_digest"],
            f"{label}.membership_digest",
            64,
            single_line=True,
        ),
        "recorded_at": timestamp(receipt["recorded_at"], f"{label}.recorded_at"),
    }
    if SHA256_RE.fullmatch(normalized["membership_digest"]) is None:
        fail("SCHEMA_INVALID", f"{label}.membership_digest must be SHA-256")
    receipt_sha256 = text(
        receipt["receipt_sha256"], f"{label}.receipt_sha256", 64, single_line=True
    )
    if SHA256_RE.fullmatch(receipt_sha256) is None or digest(normalized) != receipt_sha256:
        fail("AUTHORITY_RECEIPT_INVALID", f"{label} digest is invalid")
    return {
        **normalized,
        "receipt_sha256": receipt_sha256,
        "replayed": boolean(receipt["replayed"], f"{label}.replayed"),
    }


def authority_evidence(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        fail("SCHEMA_INVALID", f"{label} requires one to sixteen evidence references")
    result = [coarse_label(item, f"{label}[]") for item in value]
    if len(result) != len(set(result)):
        fail("SCHEMA_INVALID", f"{label} must be unique")
    return result


def validate_prepare_authority_transfer(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "transfer_id",
            "target_authority_id",
            "expected_state_revision",
            "evidence_refs",
            "now",
        },
        label="prepare-authority-transfer request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    result = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "transfer_id": identifier(request["transfer_id"], "transfer_id"),
        "target_authority_id": identifier(
            request["target_authority_id"], "target_authority_id"
        ),
        "expected_state_revision": bounded_int(
            request["expected_state_revision"],
            "expected_state_revision",
            0,
            2_147_483_647,
        ),
        "evidence_refs": authority_evidence(request["evidence_refs"], "evidence_refs"),
        "now": timestamp(request["now"]),
    }
    reject_sensitive(result, "prepare authority transfer")
    return result


def validate_stage_federation(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "transfer_id",
            "expected_state_revision",
            "source_receipts",
            "evidence_refs",
            "now",
        },
        label="stage-federation request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    raw_receipts = request["source_receipts"]
    if not isinstance(raw_receipts, list) or not 2 <= len(raw_receipts) <= 16:
        fail("SCHEMA_INVALID", "stage federation requires two to sixteen sources")
    receipts = [
        validate_authority_receipt(item, "source_receipts[]")
        for item in raw_receipts
    ]
    source_ids = [receipt["subject_authority_id"] for receipt in receipts]
    if len(source_ids) != len(set(source_ids)):
        fail("SCHEMA_INVALID", "source authority identities must be unique")
    result = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "transfer_id": identifier(request["transfer_id"], "transfer_id"),
        "expected_state_revision": bounded_int(
            request["expected_state_revision"],
            "expected_state_revision",
            0,
            2_147_483_647,
        ),
        "source_receipts": sorted(
            receipts, key=lambda item: item["subject_authority_id"]
        ),
        "evidence_refs": authority_evidence(request["evidence_refs"], "evidence_refs"),
        "now": timestamp(request["now"]),
    }
    reject_sensitive(result, "stage federation")
    return result


def validate_finalize_authority_transfer(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "transfer_id",
            "target_stage_receipt",
            "now",
        },
        label="finalize-authority-transfer request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    result = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "transfer_id": identifier(request["transfer_id"], "transfer_id"),
        "target_stage_receipt": validate_authority_receipt(
            request["target_stage_receipt"], "target_stage_receipt"
        ),
        "now": timestamp(request["now"]),
    }
    reject_sensitive(result, "finalize authority transfer")
    return result


def validate_activate_federation(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "transfer_id",
            "source_finalize_receipts",
            "evidence_refs",
            "now",
        },
        label="activate-federation request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    raw_receipts = request["source_finalize_receipts"]
    if not isinstance(raw_receipts, list) or not 2 <= len(raw_receipts) <= 16:
        fail("SCHEMA_INVALID", "federation activation requires all source receipts")
    receipts = [
        validate_authority_receipt(item, "source_finalize_receipts[]")
        for item in raw_receipts
    ]
    source_ids = [receipt["subject_authority_id"] for receipt in receipts]
    if len(source_ids) != len(set(source_ids)):
        fail("SCHEMA_INVALID", "source authority identities must be unique")
    result = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "transfer_id": identifier(request["transfer_id"], "transfer_id"),
        "source_finalize_receipts": sorted(
            receipts, key=lambda item: item["subject_authority_id"]
        ),
        "evidence_refs": authority_evidence(request["evidence_refs"], "evidence_refs"),
        "now": timestamp(request["now"]),
    }
    reject_sensitive(result, "activate federation")
    return result


def validate_enable_subordinate(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "transfer_id",
            "target_activation_receipt",
            "now",
        },
        label="enable-subordinate request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    result = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "transfer_id": identifier(request["transfer_id"], "transfer_id"),
        "target_activation_receipt": validate_authority_receipt(
            request["target_activation_receipt"], "target_activation_receipt"
        ),
        "now": timestamp(request["now"]),
    }
    reject_sensitive(result, "enable subordinate")
    return result


def validate_abort_authority_transfer(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "transfer_id",
            "expected_authority_state",
            "expected_state_revision",
            "target_activation_absent",
            "reason_code",
            "evidence_refs",
            "now",
        },
        label="abort-authority-transfer request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    result = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "transfer_id": identifier(request["transfer_id"], "transfer_id"),
        "expected_authority_state": enum(
            request["expected_authority_state"],
            "expected_authority_state",
            {"SOURCE_PREPARED", "TARGET_STAGED"},
        ),
        "expected_state_revision": bounded_int(
            request["expected_state_revision"],
            "expected_state_revision",
            0,
            2_147_483_647,
        ),
        "target_activation_absent": boolean(
            request["target_activation_absent"], "target_activation_absent"
        ),
        "reason_code": identifier(request["reason_code"], "reason_code"),
        "evidence_refs": authority_evidence(request["evidence_refs"], "evidence_refs"),
        "now": timestamp(request["now"]),
    }
    reject_sensitive(result, "abort authority transfer")
    return result


def validate_dispatcher_adoption(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "adoption_mode",
            "plugin_version",
            "proofs",
            "now",
        },
        label="dispatcher adoption request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    if request["adoption_mode"] != "COVERED_PATH_GUARDRAIL":
        fail(
            "DISPATCHER_ADOPTION_INVALID",
            "only covered-path dispatcher adoption is supported",
        )
    plugin_version = text(
        request["plugin_version"], "plugin_version", 80, single_line=True
    )
    if (
        re.fullmatch(
            r"(?:0\.3\.(?:0|1|2|3|4|5|6)|0\.4\.0)(?:\+codex\.\d{14})?",
            plugin_version,
        )
        is None
    ):
        fail(
            "DISPATCHER_ADOPTION_INVALID",
            "plugin version is incompatible with this adoption contract",
        )
    proofs = strict(
        request["proofs"],
        {
            "pre_tool_denial_verified",
            "typed_mcp_control_verified",
            "reserved_create_admission_verified",
            "lifecycle_debt_clear_verified",
            "archive_refill_fence_verified",
            "no_side_effect_canary_verified",
            "hosted_paths_uncovered",
            "universal_coverage_claimed",
        },
        label="dispatcher adoption proofs",
    )
    required_true = {
        "pre_tool_denial_verified",
        "typed_mcp_control_verified",
        "reserved_create_admission_verified",
        "lifecycle_debt_clear_verified",
        "archive_refill_fence_verified",
        "no_side_effect_canary_verified",
        "hosted_paths_uncovered",
    }
    if any(proofs[key] is not True for key in required_true):
        fail(
            "DISPATCHER_ADOPTION_UNPROVEN",
            "every covered-path adoption proof must be explicitly true",
        )
    if proofs["universal_coverage_claimed"] is not False:
        fail(
            "UNIVERSAL_ENFORCEMENT_UNPROVEN",
            "covered-path adoption cannot claim universal enforcement",
        )
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "adoption_mode": request["adoption_mode"],
        "plugin_version": plugin_version,
        "proofs": proofs,
        "now": timestamp(request["now"]),
    }


def string_list(value: Any, label: str, *, maximum: int = 100) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        fail("SCHEMA_INVALID", f"{label} must be a bounded list")
    result = [text(item, f"{label}[]", 2000, single_line=True) for item in value]
    reject_sensitive(result, label)
    return result


def validate_prepare(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "source_event_key",
            "idempotency_key",
            "outcome_key",
            "task_id",
            "title",
            "prompt",
            "priority",
            "target",
            "context",
            "dependencies",
            "permissions",
            "prohibitions",
            "privacy_boundary",
            "evidence_contract",
            "cleanup_duty",
            "lease_expires_at",
            "now",
        },
        {"duration_estimate", "public_metadata"},
        label="prepare-launch request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    output = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "source_event_key": identifier(request["source_event_key"], "source_event_key"),
        "idempotency_key": identifier(request["idempotency_key"], "idempotency_key"),
        "outcome_key": identifier(request["outcome_key"], "outcome_key"),
        "task_id": identifier(request["task_id"], "task_id"),
        "title": text(request["title"], "title", 500, single_line=True),
        "prompt": text(request["prompt"], "prompt"),
        "priority": bounded_int(request["priority"], "priority", 0, 1000),
        "target": normalize_target(request["target"]),
        "context": validate_context(request["context"], "task-launch"),
        "dependencies": string_list(request["dependencies"], "dependencies"),
        "permissions": string_list(request["permissions"], "permissions"),
        "prohibitions": string_list(request["prohibitions"], "prohibitions"),
        "privacy_boundary": text(request["privacy_boundary"], "privacy_boundary", 1000, single_line=True),
        "evidence_contract": string_list(request["evidence_contract"], "evidence_contract"),
        "cleanup_duty": string_list(request["cleanup_duty"], "cleanup_duty"),
        "lease_expires_at": timestamp(request["lease_expires_at"], "lease_expires_at"),
        "now": timestamp(request["now"]),
    }
    if output["task_id"].casefold() == "root":
        fail(
            "ROOT_WORKER_DENIED",
            "root is the control plane and cannot reserve worker capacity",
            exit_status=EXIT_CONFLICT,
        )
    output["duration_estimate"] = validate_duration_estimate(
        request.get("duration_estimate"),
        task_family_fallback=output["context"]["task_kind"],
        environment_fallback=output["context"]["environment"],
    )
    if request.get("public_metadata") is not None:
        output["public_metadata"] = validate_public_metadata(
            request["public_metadata"]
        )
    if output["context"]["repo"] != output["target"]["remote"]:
        fail("SCHEMA_INVALID", "context.repo must equal normalized target.remote")
    if output["context"]["path"] != output["target"]["path"]:
        fail("SCHEMA_INVALID", "context.path must equal target.path")
    reject_sensitive(output, "prepare-launch request")
    return output


def validate_policy_update(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "expected_policy_revision",
            "rule",
            "now",
        },
        label="record-policy-rule request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    rule = validate_rule(request["rule"])
    if rule["provenance"]["source_kind"] == "canonical":
        fail(
            "SCHEMA_INVALID",
            "runtime policy updates require scoped non-canonical provenance",
        )
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "expected_policy_revision": bounded_int(
            request["expected_policy_revision"],
            "expected_policy_revision",
            1,
            1_000_000,
        ),
        "rule": rule,
        "now": timestamp(request["now"]),
    }


def validate_effective_rules(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {"interface_version", "request_id", "context", "now"},
        label="effective-rules request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "context": validate_context(request["context"], "task-launch"),
        "now": timestamp(request["now"]),
    }


def validate_classify(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "context",
            "action_type",
            "target_alias",
            "authorization_scope",
            "policy_snapshot_revision",
            "state_revision",
            "authorized",
            "reversible",
            "destructive",
            "external_effect",
            "auto_publish",
            "identity_change",
            "credential_needed",
            "cost_change",
            "force_or_admin",
            "gate_type",
            "now",
        },
        label="classify-decision request",
    )
    if request["interface_version"] != INTERFACE_VERSION or request["gate_type"] not in GATES:
        fail("SCHEMA_INVALID", "interface_version or gate_type is invalid")
    if request["action_type"] not in ACTION_TYPES:
        fail("DECISION_DENIED", "unknown action_type is denied to the orchestrator")
    for key in (
        "authorized",
        "reversible",
        "destructive",
        "external_effect",
        "auto_publish",
        "identity_change",
        "credential_needed",
        "cost_change",
        "force_or_admin",
    ):
        if not isinstance(request[key], bool):
            fail("SCHEMA_INVALID", f"{key} must be a boolean")
    output = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "context": validate_context(request["context"], "decision-classification"),
        "action_type": identifier(request["action_type"], "action_type"),
        "target_alias": text(request["target_alias"], "target_alias", 300, single_line=True),
        "authorization_scope": identifier(
            request["authorization_scope"], "authorization_scope"
        ),
        "policy_snapshot_revision": bounded_int(
            request["policy_snapshot_revision"],
            "policy_snapshot_revision",
            1,
            1_000_000,
        ),
        "state_revision": bounded_int(
            request["state_revision"], "state_revision", 0, 2_147_483_647
        ),
        "authorized": request["authorized"],
        "reversible": request["reversible"],
        "destructive": request["destructive"],
        "external_effect": request["external_effect"],
        "auto_publish": request["auto_publish"],
        "identity_change": request["identity_change"],
        "credential_needed": request["credential_needed"],
        "cost_change": request["cost_change"],
        "force_or_admin": request["force_or_admin"],
        "gate_type": request["gate_type"],
        "now": timestamp(request["now"]),
    }
    reject_sensitive(output, "classify request")
    return output


def validate_receipt(value: Any, kind: str) -> dict[str, Any]:
    required = {
        "interface_version",
        "request_id",
        "task_id",
        "policy_snapshot_revision",
        "lease_epoch",
        "fencing_token",
        "now",
    }
    if kind == "launch":
        required |= {
            "external_thread_id",
            "applicable_rule_ids",
            "runtime_attestation",
        }
    request = strict(value, required, label=f"{kind} receipt")
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    output = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "task_id": identifier(request["task_id"], "task_id"),
        "policy_snapshot_revision": bounded_int(request["policy_snapshot_revision"], "policy_snapshot_revision", 1, 1_000_000),
        "lease_epoch": bounded_int(request["lease_epoch"], "lease_epoch", 1, 1_000_000),
        "fencing_token": bounded_int(request["fencing_token"], "fencing_token", 1, 2_147_483_647),
        "now": timestamp(request["now"]),
    }
    if kind == "launch":
        output["external_thread_id"] = identifier(request["external_thread_id"], "external_thread_id")
        output["applicable_rule_ids"] = string_list(request["applicable_rule_ids"], "applicable_rule_ids")
        raw_runtime = strict(
            request["runtime_attestation"],
            {
                "root_model",
                "root_reasoning_effort",
                "root_service_tier",
                "root_fast_mode",
                "worker_model",
                "worker_reasoning_effort",
                "worker_service_tier",
                "worker_fast_mode",
                "service_tier_attestation",
                "tier_provenance",
                "auth_mode",
                "history_mode",
                "parent_attestation_present",
            },
            label="runtime_attestation",
        )
        runtime = {
            "root_model": enum(
                raw_runtime["root_model"], "root_model", {REQUIRED_ROOT_MODEL}
            ),
            "root_reasoning_effort": enum(
                raw_runtime["root_reasoning_effort"],
                "root_reasoning_effort",
                {REQUIRED_ROOT_REASONING_EFFORT},
            ),
            "root_service_tier": enum(
                raw_runtime["root_service_tier"],
                "root_service_tier",
                {REQUIRED_SERVICE_TIER},
            ),
            "root_fast_mode": boolean(
                raw_runtime["root_fast_mode"], "root_fast_mode"
            ),
            "worker_model": enum(
                raw_runtime["worker_model"], "worker_model", {REQUIRED_ROOT_MODEL}
            ),
            "worker_reasoning_effort": enum(
                raw_runtime["worker_reasoning_effort"],
                "worker_reasoning_effort",
                {REQUIRED_ROOT_REASONING_EFFORT},
            ),
            "worker_service_tier": enum(
                raw_runtime["worker_service_tier"],
                "worker_service_tier",
                {REQUIRED_SERVICE_TIER},
            ),
            "worker_fast_mode": boolean(
                raw_runtime["worker_fast_mode"], "worker_fast_mode"
            ),
            "service_tier_attestation": enum(
                raw_runtime["service_tier_attestation"],
                "service_tier_attestation",
                {"runtime", "config-verified", "unattested"},
            ),
            "tier_provenance": enum(
                raw_runtime["tier_provenance"],
                "tier_provenance",
                {"platform-runtime", "trusted-project-and-user-config", "none"},
            ),
            "auth_mode": enum(
                raw_runtime["auth_mode"],
                "auth_mode",
                {"subscription", "api-key"},
            ),
            "history_mode": enum(
                raw_runtime["history_mode"],
                "history_mode",
                {"none", "bounded", "full-history"},
            ),
            "parent_attestation_present": boolean(
                raw_runtime["parent_attestation_present"],
                "parent_attestation_present",
            ),
        }
        if not runtime["root_fast_mode"] or not runtime["worker_fast_mode"]:
            fail("FAST_MODE_DRIFT", "root and worker fast mode must be enabled")
        if runtime["service_tier_attestation"] == "unattested":
            fail(
                "SERVICE_TIER_UNATTESTED",
                "launch surface did not verify the effective fast service tier",
            )
        expected_provenance = (
            "platform-runtime"
            if runtime["service_tier_attestation"] == "runtime"
            else "trusted-project-and-user-config"
        )
        if runtime["tier_provenance"] != expected_provenance:
            fail(
                "SERVICE_TIER_PROVENANCE_INVALID",
                "service-tier verification provenance contradicts its source",
            )
        if runtime["auth_mode"] != "subscription":
            fail(
                "FAST_AUTH_MODE_UNSUPPORTED",
                "Subscription priority-tier semantics cannot be claimed for API-key auth",
            )
        if not runtime["parent_attestation_present"]:
            fail(
                "PARENT_RUNTIME_UNATTESTED",
                "worker launch requires a verified root runtime attestation",
            )
        if (
            runtime["history_mode"] == "full-history"
            and not runtime["parent_attestation_present"]
        ):
            fail(
                "FULL_HISTORY_PARENT_UNVERIFIED",
                "full-history inheritance requires a verified parent",
            )
        output["runtime_attestation"] = runtime
    return output


def validate_handback(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "handback_id",
            "task_id",
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
            "external_thread_id",
            "disposition",
            "exact_refs",
            "checks",
            "review_findings",
            "hosted_ci",
            "deployment_state",
            "privacy_boundary",
            "artifacts",
            "resources",
            "dependencies",
            "next_action",
            "successor_request",
            "block",
            "now",
        },
        {"capacity", "public_metadata"},
        label="record-handback request",
    )
    base = validate_receipt(
        {
            key: request[key]
            for key in (
                "interface_version",
                "request_id",
                "task_id",
                "policy_snapshot_revision",
                "lease_epoch",
                "fencing_token",
                "now",
            )
        },
        "archive",
    )
    if request["disposition"] not in {"completed", "blocked", "failed", "superseded", "duplicate"}:
        fail("SCHEMA_INVALID", "handback disposition is invalid")
    exact_input = strict(
        request["exact_refs"],
        {"base_sha", "candidate_sha", "pr_url", "merge_sha", "default_sha"},
        label="exact_refs",
    )
    exact_refs: dict[str, str | None] = {}
    for key in ("base_sha", "candidate_sha", "merge_sha", "default_sha"):
        value = exact_input[key]
        if value is not None:
            value = text(value, f"exact_refs.{key}", 40, single_line=True).lower()
            if not SHA_RE.fullmatch(value):
                fail("SCHEMA_INVALID", f"exact_refs.{key} must be a full SHA")
        exact_refs[key] = value
    exact_refs["pr_url"] = (
        None
        if exact_input["pr_url"] is None
        else safe_http_url(exact_input["pr_url"], "exact_refs.pr_url")
    )
    if exact_refs["base_sha"] is None:
        fail("HANDBACK_INCOMPLETE", "handback requires the exact base SHA")
    zero_change_completion = (
        request["disposition"] == "completed"
        and request["deployment_state"] == "not_performed"
        and exact_refs["candidate_sha"] == exact_refs["base_sha"]
        and all(
            exact_refs[key] is None
            for key in ("pr_url", "merge_sha", "default_sha")
        )
    )
    if request["disposition"] == "completed" and not zero_change_completion and any(
        exact_refs[key] is None
        for key in ("candidate_sha", "pr_url", "merge_sha", "default_sha")
    ):
        fail(
            "HANDBACK_INCOMPLETE",
            "completed handback requires candidate, PR, merge, and default refs",
        )
    if (
        request["disposition"] == "completed"
        and not zero_change_completion
        and exact_refs["merge_sha"] != exact_refs["default_sha"]
    ):
        fail(
            "HANDBACK_INCOMPLETE",
            "completed handback must identify the exact merged default SHA",
        )
    if not isinstance(request["checks"], list) or not request["checks"]:
        fail("HANDBACK_INCOMPLETE", "handback requires typed checks")
    checks = []
    for item in request["checks"]:
        item = strict(item, {"name", "scope", "result", "evidence_ref"}, label="check")
        if item["result"] not in {"pass", "fail", "pending", "skipped", "blocked", "unexecuted"}:
            fail("SCHEMA_INVALID", "check result is invalid")
        checks.append(
            {
                "name": text(item["name"], "check.name", 200, single_line=True),
                "scope": text(item["scope"], "check.scope", 500, single_line=True),
                "result": item["result"],
                "evidence_ref": text(item["evidence_ref"], "check.evidence_ref", 2000, single_line=True),
            }
        )
    hosted = strict(
        request["hosted_ci"],
        {"status", "steps", "cause"},
        label="hosted_ci",
    )
    if hosted["status"] not in {"pass", "fail", "pending", "skipped", "cancelled", "unexecuted", "unavailable"}:
        fail("SCHEMA_INVALID", "hosted_ci.status is invalid")
    steps = bounded_int(hosted["steps"], "hosted_ci.steps", 0, 1_000_000)
    if steps == 0 and hosted["status"] == "pass":
        fail("CI_TRUTH_INVALID", "zero-step CI cannot be passing")
    resources = []
    if not isinstance(request["resources"], list):
        fail("SCHEMA_INVALID", "resources must be a list")
    for item in request["resources"]:
        item = strict(item, {"id", "disposition", "reason"}, {"bytes"}, "resource")
        if item["disposition"] not in {"retain", "remove", "removed"}:
            fail("SCHEMA_INVALID", "resource disposition is invalid")
        byte_count = item.get("bytes", 0)
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            fail("SCHEMA_INVALID", "resource bytes is invalid")
        resources.append(
            {
                "id": text(item["id"], "resource.id", 500, single_line=True),
                "disposition": item["disposition"],
                "reason": text(item["reason"], "resource.reason", 1000, single_line=True),
                "bytes": byte_count,
            }
        )
    if request["disposition"] in {"completed", "superseded", "duplicate"} and not resources:
        fail("HANDBACK_INCOMPLETE", "terminal handback requires resource disposition")
    raw_capacity = request.get("capacity")
    if request["disposition"] != "blocked" and raw_capacity is None:
        fail(
            "REFILL_PROOF_REQUIRED",
            "terminal handback requires explicit recycle/refill capacity proof",
        )
    if raw_capacity is None:
        raw_capacity = {
            "configured_capacity": 1,
            "runnable_queue_count": 0,
            "terminal_status": "completed",
            "clean_handback": True,
            "empty_outcome": "EMPTY",
            "evidence_refs": ["blocked-nonterminal"],
            "blocked_audits": [],
        }
    raw_capacity = strict(
        raw_capacity,
        {
            "configured_capacity",
            "runnable_queue_count",
            "terminal_status",
            "clean_handback",
            "empty_outcome",
            "evidence_refs",
            "blocked_audits",
        },
        label="handback capacity",
    )
    if raw_capacity["terminal_status"] not in {
        "completed",
        "archived",
        "interrupted/notLoaded",
    }:
        fail("SCHEMA_INVALID", "capacity terminal_status is invalid")
    if not isinstance(raw_capacity["clean_handback"], bool):
        fail("SCHEMA_INVALID", "capacity clean_handback must be a boolean")
    if not raw_capacity["clean_handback"]:
        fail(
            "HANDBACK_INCOMPLETE",
            "capacity release requires a valid clean handback",
        )
    if (
        raw_capacity["terminal_status"] == "interrupted/notLoaded"
        and request["disposition"] != "completed"
    ):
        fail(
            "HANDBACK_INCOMPLETE",
            "interrupted/notLoaded is terminal only with completed clean evidence",
        )
    if raw_capacity["empty_outcome"] not in {"EMPTY", "OWNER_GATED"}:
        fail("SCHEMA_INVALID", "capacity empty_outcome is invalid")
    capacity_evidence = (
        [
            coarse_label(reference, "capacity.evidence_refs[]")
            for reference in raw_capacity["evidence_refs"]
        ]
        if isinstance(raw_capacity["evidence_refs"], list)
        else []
    )
    if not capacity_evidence:
        fail("HANDBACK_INCOMPLETE", "capacity outcome requires evidence")
    capacity = {
        "configured_capacity": bounded_int(
            raw_capacity["configured_capacity"],
            "capacity.configured_capacity",
            1,
            64,
        ),
        "runnable_queue_count": bounded_int(
            raw_capacity["runnable_queue_count"],
            "capacity.runnable_queue_count",
            0,
            1_000_000,
        ),
        "terminal_status": raw_capacity["terminal_status"],
        "clean_handback": raw_capacity["clean_handback"],
        "empty_outcome": raw_capacity["empty_outcome"],
        "evidence_refs": capacity_evidence,
        "blocked_audits": validate_blocked_audits(
            raw_capacity["blocked_audits"], "capacity.blocked_audits"
        ),
    }
    output = {
        **base,
        "handback_id": identifier(request["handback_id"], "handback_id"),
        "disposition": request["disposition"],
        "exact_refs": exact_refs,
        "checks": checks,
        "review_findings": string_list(request["review_findings"], "review_findings"),
        "hosted_ci": {
            "status": hosted["status"],
            "steps": steps,
            "cause": text(hosted["cause"], "hosted_ci.cause", 500, single_line=True),
        },
        "deployment_state": text(
            request["deployment_state"],
            "deployment_state",
            100,
            single_line=True,
        ),
        "privacy_boundary": text(request["privacy_boundary"], "privacy_boundary", 1000, single_line=True),
        "artifacts": string_list(request["artifacts"], "artifacts"),
        "resources": resources,
        "dependencies": string_list(request["dependencies"], "dependencies"),
        "next_action": text(request["next_action"], "next_action", 2000, single_line=True),
        "successor_request": request["successor_request"],
        "block": request["block"],
        "capacity": capacity,
        "external_thread_id": identifier(
            request["external_thread_id"], "external_thread_id"
        ),
    }
    if request.get("public_metadata") is not None:
        output["public_metadata"] = validate_public_metadata(
            request["public_metadata"]
        )
    if output["deployment_state"] not in {
        "not_performed",
        "local_only",
        "owner_authorized_deployed",
        "unavailable",
    }:
        fail("SCHEMA_INVALID", "deployment_state is invalid")
    if output["disposition"] == "blocked":
        block = strict(
            output["block"],
            {"classification", "reason_code", "evidence_refs"},
            label="handback block",
        )
        if block["classification"] not in {
            "owner_gate",
            "dependency",
            "resource_budget",
            "transient_tool",
            "zero_step_ci",
            "stale_dashboard",
            "completed_external",
            "policy_conflict",
            "unknown",
        }:
            fail("SCHEMA_INVALID", "block classification is invalid")
        output["block"] = {
            "classification": block["classification"],
            "reason_code": identifier(block["reason_code"], "block.reason_code"),
            "evidence_refs": string_list(block["evidence_refs"], "block.evidence_refs"),
        }
    elif output["block"] is not None:
        fail("SCHEMA_INVALID", "block must be null for a non-blocked disposition")
    if output["successor_request"] is not None:
        validate_prepare(output["successor_request"])
    reject_sensitive(output, "handback")
    return output


def validate_blocked_audits(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        fail("SCHEMA_INVALID", f"{label} must be a list")
    classifications = {
        "owner_gate",
        "dependency",
        "resource_budget",
        "transient_tool",
        "zero_step_ci",
        "stale_dashboard",
        "completed_external",
        "policy_conflict",
        "unknown",
    }
    audits = []
    for item in value:
        item = strict(
            item,
            {
                "task_id",
                "classification",
                "outcome",
                "reason_code",
                "evidence_refs",
            },
            label=f"{label} item",
        )
        if item["classification"] not in classifications or item["outcome"] not in {
            "resume",
            "archive",
            "remain_blocked",
            "owner_gate",
        }:
            fail("SCHEMA_INVALID", "audit classification or outcome is invalid")
        if item["classification"] == "owner_gate" and item["outcome"] != "owner_gate":
            fail("SCHEMA_INVALID", "owner-gate audit cannot auto-resume")
        audits.append(
            {
                "task_id": identifier(item["task_id"], "audit.task_id"),
                "classification": item["classification"],
                "outcome": item["outcome"],
                "reason_code": identifier(item["reason_code"], "audit.reason_code"),
                "evidence_refs": (
                    [
                        coarse_label(reference, "audit.evidence_refs[]")
                        for reference in item["evidence_refs"]
                    ]
                    if isinstance(item["evidence_refs"], list)
                    else []
                ),
            }
        )
    return audits


def validate_recycle(value: Any) -> dict[str, Any]:
    request = strict(value, {"interface_version", "request_id", "audits", "now"}, label="recycle request")
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "recycle interface version is unsupported")
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "audits": validate_blocked_audits(request["audits"], "recycle audits"),
        "now": timestamp(request["now"]),
    }


def validate_capacity_reconfiguration(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "expected_state_revision",
            "expected_configured_capacity",
            "requested_configured_capacity",
            "evidence_refs",
            "now",
        },
        label="configure-capacity request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    evidence_refs = [
        coarse_label(reference, "configure-capacity.evidence_refs[]")
        for reference in request["evidence_refs"]
    ] if isinstance(request["evidence_refs"], list) else []
    if not evidence_refs or len(evidence_refs) > 16:
        fail(
            "SCHEMA_INVALID",
            "configure-capacity requires one to sixteen coarse evidence references",
        )
    output = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "expected_state_revision": bounded_int(
            request["expected_state_revision"],
            "expected_state_revision",
            0,
            9_223_372_036_854_775_807,
        ),
        "expected_configured_capacity": bounded_int(
            request["expected_configured_capacity"],
            "expected_configured_capacity",
            1,
            64,
        ),
        "requested_configured_capacity": bounded_int(
            request["requested_configured_capacity"],
            "requested_configured_capacity",
            1,
            64,
        ),
        "evidence_refs": evidence_refs,
        "now": timestamp(request["now"]),
    }
    if (
        output["expected_configured_capacity"]
        == output["requested_configured_capacity"]
    ):
        fail(
            "CAPACITY_NO_CHANGE",
            "capacity reconfiguration must request a different bounded value",
            exit_status=EXIT_CONFLICT,
        )
    reject_sensitive(output, "configure-capacity request")
    return output


def validate_capacity_watchdog(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "saga_id",
            "configured_capacity",
            "runnable_queue_count",
            "empty_outcome",
            "evidence_refs",
            "successor_request",
            "now",
        },
        {"blocked_audits"},
        label="capacity-watchdog request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    if request["empty_outcome"] not in {"EMPTY", "OWNER_GATED"}:
        fail("SCHEMA_INVALID", "capacity watchdog empty_outcome is invalid")
    evidence_refs = string_list(
        request["evidence_refs"], "capacity-watchdog.evidence_refs"
    )
    if not evidence_refs:
        fail("SCHEMA_INVALID", "capacity watchdog requires evidence")
    successor = request["successor_request"]
    if successor is not None:
        successor = validate_prepare(successor)
    output = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "saga_id": identifier(request["saga_id"], "saga_id"),
        "configured_capacity": bounded_int(
            request["configured_capacity"], "configured_capacity", 1, 64
        ),
        "runnable_queue_count": bounded_int(
            request["runnable_queue_count"], "runnable_queue_count", 0, 1_000_000
        ),
        "empty_outcome": request["empty_outcome"],
        "evidence_refs": evidence_refs,
        "successor_request": successor,
        "blocked_audits": validate_blocked_audits(
            request.get("blocked_audits", []),
            "capacity watchdog blocked_audits",
        ),
        "now": timestamp(request["now"]),
    }
    reject_sensitive(output, "capacity watchdog")
    return output


def validate_lifecycle_watchdog(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "task_id",
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
            "external_thread_id",
            "action",
            "trigger",
            "worker_status",
            "completion_signals",
            "evidence_refs",
            "remaining_work",
            "interrupt_receipt",
            "capacity",
            "now",
        },
        label="lifecycle-watchdog request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    if request["action"] not in {"observe", "interrupt-receipt"}:
        fail("SCHEMA_INVALID", "lifecycle watchdog action is invalid")
    if request["trigger"] not in {
        "before-status-claim",
        "interrupt-receipt",
        "wait-timeout",
        "worker-message",
    }:
        fail("SCHEMA_INVALID", "lifecycle watchdog trigger is invalid")
    if request["worker_status"] not in {
        "completed",
        "interrupted",
        "running",
        "unknown",
        "waiting",
    }:
        fail("SCHEMA_INVALID", "worker_status is invalid")
    raw_signals = string_list(
        request["completion_signals"],
        "lifecycle-watchdog.completion_signals",
        maximum=10,
    )
    if len(raw_signals) != len(set(raw_signals)):
        fail("SCHEMA_INVALID", "completion_signals must be unique")
    unknown_signals = set(raw_signals) - COMPLETION_SIGNALS
    if unknown_signals:
        fail(
            "SCHEMA_INVALID",
            "completion_signals contains an unsupported value",
            details={"signals": sorted(unknown_signals)},
        )
    evidence_refs = string_list(
        request["evidence_refs"],
        "lifecycle-watchdog.evidence_refs",
        maximum=50,
    )
    if not evidence_refs:
        fail("SCHEMA_INVALID", "lifecycle watchdog requires evidence")
    remaining_work = request["remaining_work"]
    if remaining_work is not None:
        remaining_work = strict(
            remaining_work,
            {"summary_code", "progress_ref", "observed_at", "eta_seconds"},
            label="lifecycle-watchdog remaining_work",
        )
        remaining_work = {
            "summary_code": identifier(
                remaining_work["summary_code"], "remaining_work.summary_code"
            ),
            "progress_ref": identifier(
                remaining_work["progress_ref"], "remaining_work.progress_ref"
            ),
            "observed_at": timestamp(
                remaining_work["observed_at"], "remaining_work.observed_at"
            ),
            "eta_seconds": bounded_int(
                remaining_work["eta_seconds"],
                "remaining_work.eta_seconds",
                1,
                86_400,
            ),
        }
    interrupt_receipt = request["interrupt_receipt"]
    if interrupt_receipt is not None:
        interrupt_receipt = strict(
            interrupt_receipt,
            {"receipt_id", "external_thread_id"},
            label="lifecycle-watchdog interrupt_receipt",
        )
        interrupt_receipt = {
            "receipt_id": identifier(
                interrupt_receipt["receipt_id"], "interrupt_receipt.receipt_id"
            ),
            "external_thread_id": identifier(
                interrupt_receipt["external_thread_id"],
                "interrupt_receipt.external_thread_id",
            ),
        }
    capacity = request["capacity"]
    if capacity is not None:
        capacity = strict(
            capacity,
            {
                "configured_capacity",
                "runnable_queue_count",
                "empty_outcome",
                "evidence_refs",
                "blocked_audits",
                "successor_request",
            },
            label="lifecycle-watchdog capacity",
        )
        capacity_evidence = string_list(
            capacity["evidence_refs"],
            "lifecycle-watchdog.capacity.evidence_refs",
        )
        if not capacity_evidence:
            fail("SCHEMA_INVALID", "interrupt receipt capacity requires evidence")
        successor = capacity["successor_request"]
        if successor is not None:
            successor = validate_prepare(successor)
        capacity = {
            "configured_capacity": bounded_int(
                capacity["configured_capacity"], "configured_capacity", 1, 64
            ),
            "runnable_queue_count": bounded_int(
                capacity["runnable_queue_count"],
                "runnable_queue_count",
                0,
                1_000_000,
            ),
            "empty_outcome": capacity["empty_outcome"],
            "evidence_refs": capacity_evidence,
            "blocked_audits": validate_blocked_audits(
                capacity["blocked_audits"],
                "lifecycle-watchdog capacity blocked_audits",
            ),
            "successor_request": successor,
        }
        if capacity["empty_outcome"] not in {"EMPTY", "OWNER_GATED"}:
            fail("SCHEMA_INVALID", "interrupt receipt empty_outcome is invalid")
    if request["action"] == "observe":
        if (
            request["trigger"] == "interrupt-receipt"
            or interrupt_receipt is not None
            or capacity is not None
            or request["worker_status"] == "interrupted"
        ):
            fail("SCHEMA_INVALID", "observe request carries interrupt-only fields")
    else:
        if (
            request["trigger"] != "interrupt-receipt"
            or request["worker_status"] != "interrupted"
            or remaining_work is not None
            or interrupt_receipt is None
            or capacity is None
        ):
            fail("SCHEMA_INVALID", "interrupt receipt request is incomplete")
        if interrupt_receipt["external_thread_id"] != request["external_thread_id"]:
            fail(
                "SCHEMA_INVALID",
                "interrupt receipt external thread does not match the request",
            )
    output = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "task_id": identifier(request["task_id"], "task_id"),
        "policy_snapshot_revision": bounded_int(
            request["policy_snapshot_revision"],
            "policy_snapshot_revision",
            1,
            1_000_000,
        ),
        "lease_epoch": bounded_int(
            request["lease_epoch"], "lease_epoch", 1, 1_000_000
        ),
        "fencing_token": bounded_int(
            request["fencing_token"], "fencing_token", 1, 2_147_483_647
        ),
        "external_thread_id": identifier(
            request["external_thread_id"], "external_thread_id"
        ),
        "action": request["action"],
        "trigger": request["trigger"],
        "worker_status": request["worker_status"],
        "completion_signals": sorted(raw_signals),
        "evidence_refs": sorted(set(evidence_refs)),
        "remaining_work": remaining_work,
        "interrupt_receipt": interrupt_receipt,
        "capacity": capacity,
        "now": timestamp(request["now"]),
    }
    if remaining_work is not None:
        observed = utc_instant(remaining_work["observed_at"])
        current = utc_instant(output["now"])
        if observed > current:
            fail("SCHEMA_INVALID", "remaining work observation cannot be future-dated")
    reject_sensitive(output, "lifecycle watchdog")
    return output


def validate_external_task(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "task_id",
            "source_event_key",
            "outcome_key",
            "external_thread_id",
            "now",
        },
        label="reconcile-external-task request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "task_id": identifier(request["task_id"], "task_id"),
        "source_event_key": identifier(
            request["source_event_key"], "source_event_key"
        ),
        "outcome_key": identifier(request["outcome_key"], "outcome_key"),
        "external_thread_id": identifier(
            request["external_thread_id"], "external_thread_id"
        ),
        "now": timestamp(request["now"]),
    }


def validate_setup_failure(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "task_id",
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
            "reason_code",
            "evidence_refs",
            "configured_capacity",
            "runnable_queue_count",
            "empty_outcome",
            "blocked_audits",
            "successor_candidates",
            "now",
        },
        label="record-setup-failure request",
    )
    base = validate_receipt(
        {
            key: request[key]
            for key in (
                "interface_version",
                "request_id",
                "task_id",
                "policy_snapshot_revision",
                "lease_epoch",
                "fencing_token",
                "now",
            )
        },
        "archive",
    )
    if request["empty_outcome"] not in {"EMPTY", "OWNER_GATED"}:
        fail("SCHEMA_INVALID", "setup failure empty_outcome is invalid")
    if not isinstance(request["successor_candidates"], list):
        fail("SCHEMA_INVALID", "successor_candidates must be a list")
    candidates = [
        validate_prepare(candidate) for candidate in request["successor_candidates"]
    ]
    task_ids = [candidate["task_id"] for candidate in candidates]
    if len(task_ids) != len(set(task_ids)):
        fail("SCHEMA_INVALID", "successor candidate task ids must be unique")
    evidence_refs = [
        coarse_label(item, "setup failure evidence_refs[]")
        for item in request["evidence_refs"]
    ] if isinstance(request["evidence_refs"], list) else []
    if not evidence_refs:
        fail("SCHEMA_INVALID", "setup failure requires evidence references")
    output = {
        **base,
        "reason_code": identifier(request["reason_code"], "reason_code"),
        "evidence_refs": evidence_refs,
        "configured_capacity": bounded_int(
            request["configured_capacity"], "configured_capacity", 1, 64
        ),
        "runnable_queue_count": bounded_int(
            request["runnable_queue_count"],
            "runnable_queue_count",
            0,
            1_000_000,
        ),
        "empty_outcome": request["empty_outcome"],
        "blocked_audits": validate_blocked_audits(
            request["blocked_audits"], "setup failure blocked_audits"
        ),
        "successor_candidates": candidates,
    }
    reject_sensitive(output, "setup failure")
    return output


def validate_actual_timing(value: Any, label: str) -> dict[str, int | None]:
    actual = strict(
        value,
        {
            "active_seconds",
            "queue_seconds",
            "setup_seconds",
            "tool_wait_seconds",
            "external_wait_seconds",
            "total_wall_seconds",
            "first_evidence_seconds",
            "safe_close_seconds",
        },
        label=label,
    )
    result: dict[str, int | None] = {
        "active_seconds": bounded_int(
            actual["active_seconds"], f"{label}.active_seconds", 0, 2_147_483_647
        ),
        "queue_seconds": optional_seconds(
            actual["queue_seconds"], f"{label}.queue_seconds"
        ),
        "setup_seconds": optional_seconds(
            actual["setup_seconds"], f"{label}.setup_seconds"
        ),
        "tool_wait_seconds": optional_seconds(
            actual["tool_wait_seconds"], f"{label}.tool_wait_seconds"
        ),
        "external_wait_seconds": optional_seconds(
            actual["external_wait_seconds"], f"{label}.external_wait_seconds"
        ),
        "total_wall_seconds": optional_seconds(
            actual["total_wall_seconds"], f"{label}.total_wall_seconds"
        ),
        "first_evidence_seconds": optional_seconds(
            actual["first_evidence_seconds"], f"{label}.first_evidence_seconds"
        ),
        "safe_close_seconds": optional_seconds(
            actual["safe_close_seconds"], f"{label}.safe_close_seconds"
        ),
    }
    wall = result["total_wall_seconds"]
    if wall is not None:
        for key, measured in result.items():
            if key != "total_wall_seconds" and measured is not None and measured > wall:
                fail(
                    "SCHEMA_INVALID",
                    f"{label}.{key} cannot exceed total wall time",
                )
    return result


def duration_fenced_base(
    request: dict[str, Any], label: str
) -> dict[str, Any]:
    base = validate_receipt(
        {
            key: request[key]
            for key in (
                "interface_version",
                "request_id",
                "task_id",
                "policy_snapshot_revision",
                "lease_epoch",
                "fencing_token",
                "now",
            )
        },
        "archive",
    )
    return {
        **base,
        "external_thread_id": identifier(
            request["external_thread_id"], f"{label}.external_thread_id"
        ),
    }


def validate_duration_progress(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "task_id",
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
            "external_thread_id",
            "runtime_state",
            "actual",
            "successor_request",
            "now",
        },
        label="record-duration-progress request",
    )
    base = duration_fenced_base(request, "duration progress")
    if request["runtime_state"] not in {"active", *NON_RUNTIME_STATES}:
        fail("SCHEMA_INVALID", "duration runtime_state is invalid")
    actual = validate_actual_timing(request["actual"], "duration progress.actual")
    successor = request["successor_request"]
    if successor is not None:
        successor = validate_prepare(successor)
    output = {
        **base,
        "runtime_state": request["runtime_state"],
        **actual,
        "actual": actual,
        "successor_request": successor,
    }
    reject_sensitive(output, "duration progress")
    return output


def validate_duration_observation(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "sample_id",
            "task_id",
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
            "external_thread_id",
            "completed",
            "actual",
            "evidence_refs",
            "now",
        },
        label="record-duration-observation request",
    )
    if request["completed"] is not True:
        fail(
            "CENSORED_SAMPLE_REJECTED",
            "only completed observations may enter calibration evidence",
        )
    base = duration_fenced_base(request, "duration observation")
    actual = validate_actual_timing(
        request["actual"], "duration observation.actual"
    )
    evidence = request["evidence_refs"]
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
        fail("SCHEMA_INVALID", "duration observation requires bounded evidence")
    safe_evidence = [
        coarse_label(item, "duration observation.evidence_refs[]")
        for item in evidence
    ]
    output = {
        **base,
        "sample_id": identifier(request["sample_id"], "sample_id"),
        "completed": True,
        **actual,
        "actual": actual,
        "evidence_refs": safe_evidence,
    }
    reject_sensitive(output, "duration observation")
    return output


def validate_duration_estimate_query(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "task_family",
            "tool_family",
            "environment_class",
            "minimum_estimate_version",
            "now",
        },
        label="duration-estimate request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    output = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "task_family": coarse_label(
            request["task_family"], "duration-estimate.task_family"
        ),
        "tool_family": coarse_label(
            request["tool_family"], "duration-estimate.tool_family"
        ),
        "environment_class": coarse_label(
            request["environment_class"], "duration-estimate.environment_class"
        ),
        "minimum_estimate_version": bounded_int(
            request["minimum_estimate_version"],
            "duration-estimate.minimum_estimate_version",
            1,
            1_000_000,
        ),
        "now": timestamp(request["now"]),
    }
    reject_sensitive(output, "duration estimate query")
    return output


def validate_resource_profile(value: Any, label: str) -> dict[str, Any]:
    profile = strict(
        value,
        {"resource_class", "exclusive_group", "weight", "cap"},
        label=label,
    )
    if profile["resource_class"] not in {"light", "heavy"}:
        fail("SCHEMA_INVALID", f"{label}.resource_class is invalid")
    exclusive_group = profile["exclusive_group"]
    if exclusive_group is not None:
        if (
            not isinstance(exclusive_group, str)
            or "/" in exclusive_group
            or "\\" in exclusive_group
            or "@" in exclusive_group
            or ":" in exclusive_group
        ):
            fail(
                "PRIVACY_REJECTED",
                f"{label}.exclusive_group must be a coarse non-path alias",
            )
        exclusive_group = coarse_label(
            exclusive_group, f"{label}.exclusive_group"
        )
    weight = bounded_int(profile["weight"], f"{label}.weight", 1, 64)
    cap = bounded_int(profile["cap"], f"{label}.cap", 1, 64)
    if weight > cap:
        fail("SCHEMA_INVALID", f"{label}.weight cannot exceed cap")
    return {
        "resource_class": profile["resource_class"],
        "exclusive_group": exclusive_group,
        "weight": weight,
        "cap": cap,
    }


def validate_duration_schedule(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "active_heavyweight",
            "heavyweight_concurrency_cap",
            "short_lane_available",
            "capacity_deficit",
            "candidates",
            "now",
        },
        {"resource_holds"},
        label="duration-schedule request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    if not isinstance(request["short_lane_available"], bool):
        fail("SCHEMA_INVALID", "short_lane_available must be boolean")
    if not isinstance(request["capacity_deficit"], bool):
        fail("SCHEMA_INVALID", "capacity_deficit must be boolean")
    if not isinstance(request["candidates"], list) or len(request["candidates"]) > 1000:
        fail("SCHEMA_INVALID", "duration candidates must be a bounded list")
    raw_holds = request.get("resource_holds", [])
    if not isinstance(raw_holds, list) or len(raw_holds) > 64:
        fail("SCHEMA_INVALID", "resource_holds must be a bounded list")
    resource_holds = []
    hold_ids: set[str] = set()
    for item in raw_holds:
        item = strict(
            item,
            {"holder_id", "state", "resource_profile"},
            label="resource hold",
        )
        holder_id = coarse_label(item["holder_id"], "resource hold.holder_id")
        if holder_id in hold_ids:
            fail("SCHEMA_INVALID", "resource hold ids must be unique")
        hold_ids.add(holder_id)
        if item["state"] not in {"active", "queued_setup"}:
            fail("SCHEMA_INVALID", "resource hold state is invalid")
        resource_holds.append(
            {
                "holder_id": holder_id,
                "state": item["state"],
                "resource_profile": validate_resource_profile(
                    item["resource_profile"], "resource hold.resource_profile"
                ),
            }
        )
    candidates = []
    seen: set[str] = set()
    for item in request["candidates"]:
        item = strict(
            item,
            {
                "candidate_id",
                "bucket",
                "runtime_state",
                "setup_state",
                "priority",
                "queue_seconds",
            },
            {"resource_profile"},
            label="duration candidate",
        )
        candidate_id = coarse_label(
            item["candidate_id"], "duration candidate.candidate_id"
        )
        if candidate_id in seen:
            fail("SCHEMA_INVALID", "duration candidate ids must be unique")
        if candidate_id in hold_ids:
            fail(
                "SCHEMA_INVALID",
                "duration candidate cannot duplicate an existing resource holder",
            )
        seen.add(candidate_id)
        if item["bucket"] not in DURATION_BUCKETS:
            fail("SCHEMA_INVALID", "duration candidate bucket is invalid")
        if item["runtime_state"] not in {"active", *NON_RUNTIME_STATES}:
            fail("SCHEMA_INVALID", "duration candidate runtime_state is invalid")
        if item["setup_state"] not in {"ready", "queued_setup", "failed"}:
            fail("SCHEMA_INVALID", "duration candidate setup_state is invalid")
        candidates.append(
            {
                "candidate_id": candidate_id,
                "bucket": item["bucket"],
                "runtime_state": item["runtime_state"],
                "setup_state": item["setup_state"],
                "priority": bounded_int(
                    item["priority"], "duration candidate.priority", 0, 1000
                ),
                "queue_seconds": bounded_int(
                    item["queue_seconds"],
                    "duration candidate.queue_seconds",
                    0,
                    2_147_483_647,
                ),
                "resource_profile": validate_resource_profile(
                    item.get(
                        "resource_profile",
                        {
                            "resource_class": "light",
                            "exclusive_group": None,
                            "weight": 1,
                            "cap": 64,
                        },
                    ),
                    "duration candidate.resource_profile",
                ),
            }
        )
    output = {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "active_heavyweight": bounded_int(
            request["active_heavyweight"], "active_heavyweight", 0, 64
        ),
        "heavyweight_concurrency_cap": bounded_int(
            request["heavyweight_concurrency_cap"],
            "heavyweight_concurrency_cap",
            1,
            64,
        ),
        "short_lane_available": request["short_lane_available"],
        "capacity_deficit": request["capacity_deficit"],
        "resource_holds": resource_holds,
        "candidates": candidates,
        "now": timestamp(request["now"]),
    }
    reject_sensitive(output, "duration schedule")
    return output


def validate_takeover(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "task_id",
            "expected_lease_epoch",
            "expected_fencing_token",
            "lease_expires_at",
            "now",
        },
        label="takeover-lease request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    now = timestamp(request["now"])
    expires = timestamp(request["lease_expires_at"], "lease_expires_at")
    if expires <= now:
        fail("SCHEMA_INVALID", "takeover lease expiry must be in the future")
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "task_id": identifier(request["task_id"], "task_id"),
        "expected_lease_epoch": bounded_int(
            request["expected_lease_epoch"], "expected_lease_epoch", 1, 1_000_000
        ),
        "expected_fencing_token": bounded_int(
            request["expected_fencing_token"], "expected_fencing_token", 1, 2_147_483_647
        ),
        "lease_expires_at": expires,
        "now": now,
    }


def validate_expired_lease_reconciliation(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "task_id",
            "policy_snapshot_revision",
            "expected_lease_epoch",
            "expected_fencing_token",
            "expected_owner_claim_id",
            "expected_external_thread_id",
            "expected_lease_expires_at",
            "now",
        },
        label="reconcile-expired-lease request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "interface version is unsupported")
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "task_id": identifier(request["task_id"], "task_id"),
        "policy_snapshot_revision": bounded_int(
            request["policy_snapshot_revision"],
            "policy_snapshot_revision",
            1,
            1_000_000,
        ),
        "expected_lease_epoch": bounded_int(
            request["expected_lease_epoch"],
            "expected_lease_epoch",
            1,
            1_000_000,
        ),
        "expected_fencing_token": bounded_int(
            request["expected_fencing_token"],
            "expected_fencing_token",
            1,
            2_147_483_647,
        ),
        "expected_owner_claim_id": identifier(
            request["expected_owner_claim_id"], "expected_owner_claim_id"
        ),
        "expected_external_thread_id": identifier(
            request["expected_external_thread_id"],
            "expected_external_thread_id",
        ),
        "expected_lease_expires_at": timestamp(
            request["expected_lease_expires_at"],
            "expected_lease_expires_at",
        ),
        "now": timestamp(request["now"]),
    }


def validate_heartbeat(value: Any) -> dict[str, Any]:
    request = strict(
        value,
        {
            "interface_version",
            "request_id",
            "task_id",
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
            "lease_expires_at",
            "now",
        },
        {"external_thread_id"},
        label="heartbeat request",
    )
    base = validate_receipt(
        {
            key: request[key]
            for key in (
                "interface_version",
                "request_id",
                "task_id",
                "policy_snapshot_revision",
                "lease_epoch",
                "fencing_token",
                "now",
            )
        },
        "archive",
    )
    expires = timestamp(request["lease_expires_at"], "lease_expires_at")
    if expires <= base["now"]:
        fail("SCHEMA_INVALID", "heartbeat lease expiry must be in the future")
    return {
        **base,
        "lease_expires_at": expires,
        "external_thread_id": (
            None
            if request.get("external_thread_id") is None
            else identifier(
                request["external_thread_id"], "external_thread_id"
            )
        ),
    }


def validate_migration(value: Any) -> dict[str, Any]:
    request = strict(value, {"interface_version", "request_id", "input_path", "dry_run", "now"}, label="migration request")
    if request["interface_version"] != INTERFACE_VERSION or not isinstance(request["dry_run"], bool):
        fail("SCHEMA_INVALID", "migration interface or dry_run is invalid")
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "input_path": text(request["input_path"], "input_path", 4000, single_line=True),
        "dry_run": request["dry_run"],
        "now": timestamp(request["now"]),
    }


def emit_success(operation: str, result: Any) -> None:
    print(canonical({"interface_version": INTERFACE_VERSION, "ok": True, "operation": operation, "result": result}))


def emit_error(error: ControlError) -> int:
    print(
        canonical(
            {
                "interface_version": INTERFACE_VERSION,
                "ok": False,
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                },
            }
        ),
        file=sys.stderr,
    )
    return error.exit_status


def parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parent
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--state-dir", default=str(root / "state"))
    result.add_argument("--policy-ledger", default=str(root / "policy-ledger.json"))
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--now", required=True)
    init.add_argument("--configured-capacity", type=int, default=4)
    for name in (
        "record-policy-rule",
        "prepare-authority-transfer",
        "stage-federation",
        "finalize-authority-transfer",
        "activate-federation",
        "enable-subordinate",
        "abort-authority-transfer",
        "prepare-launch",
        "effective-rules",
        "classify-decision",
        "classify-root-action",
        "record-launch-receipt",
        "reconcile-external-task",
        "record-setup-failure",
        "record-handback",
        "record-archive-receipt",
        "configure-capacity",
        "capacity-watchdog",
        "lifecycle-watchdog",
        "takeover-lease",
        "reconcile-expired-lease",
        "record-heartbeat",
        "record-duration-progress",
        "record-duration-observation",
        "duration-estimate",
        "duration-schedule",
        "recycle-queue",
        "record-dispatcher-adoption",
        "migrate-decisions",
    ):
        command = commands.add_parser(name)
        command.add_argument("--request", required=True)
    status = commands.add_parser("status")
    status.add_argument("--now")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        state_dir = safe_state_dir(args.state_dir)
        ledger = Path(args.policy_ledger).resolve()
        plane = Plane(state_dir, ledger)
        operations: dict[str, tuple[Callable[[Any], Any], str]] = {
            "record-policy-rule": (plane.record_rule, "record-policy-rule"),
            "prepare-authority-transfer": (
                plane.prepare_authority_transfer,
                "prepare-authority-transfer",
            ),
            "stage-federation": (plane.stage_federation, "stage-federation"),
            "finalize-authority-transfer": (
                plane.finalize_authority_transfer,
                "finalize-authority-transfer",
            ),
            "activate-federation": (
                plane.activate_federation,
                "activate-federation",
            ),
            "enable-subordinate": (
                plane.enable_subordinate,
                "enable-subordinate",
            ),
            "abort-authority-transfer": (
                plane.abort_authority_transfer,
                "abort-authority-transfer",
            ),
            "prepare-launch": (plane.prepare_launch, "prepare-launch"),
            "effective-rules": (plane.effective_rules, "effective-rules"),
            "classify-decision": (plane.classify, "classify-decision"),
            "classify-root-action": (
                plane.classify_root_action,
                "classify-root-action",
            ),
            "record-launch-receipt": (plane.launch_receipt, "record-launch-receipt"),
            "reconcile-external-task": (
                plane.reconcile_external_task,
                "reconcile-external-task",
            ),
            "record-setup-failure": (
                plane.record_setup_failure,
                "record-setup-failure",
            ),
            "record-handback": (plane.record_handback, "record-handback"),
            "record-archive-receipt": (plane.archive_receipt, "record-archive-receipt"),
            "configure-capacity": (
                plane.configure_capacity,
                "configure-capacity",
            ),
            "capacity-watchdog": (plane.capacity_watchdog, "capacity-watchdog"),
            "lifecycle-watchdog": (plane.lifecycle_watchdog, "lifecycle-watchdog"),
            "takeover-lease": (plane.takeover_lease, "takeover-lease"),
            "reconcile-expired-lease": (
                plane.reconcile_expired_lease,
                "reconcile-expired-lease",
            ),
            "record-heartbeat": (plane.heartbeat, "record-heartbeat"),
            "record-duration-progress": (
                plane.record_duration_progress,
                "record-duration-progress",
            ),
            "record-duration-observation": (
                plane.record_duration_observation,
                "record-duration-observation",
            ),
            "duration-estimate": (plane.duration_estimate, "duration-estimate"),
            "duration-schedule": (plane.duration_schedule, "duration-schedule"),
            "recycle-queue": (plane.recycle, "recycle-queue"),
            "record-dispatcher-adoption": (
                plane.record_dispatcher_adoption,
                "record-dispatcher-adoption",
            ),
            "migrate-decisions": (plane.migrate, "migrate-decisions"),
        }
        if args.command == "init":
            emit_success(
                "init",
                plane.initialize(args.now, args.configured_capacity),
            )
        elif args.command == "status":
            emit_success("status", plane.status(args.now))
        else:
            function, operation = operations[args.command]
            emit_success(operation, function(read_json(args.request)))
        return 0
    except ControlError as error:
        return emit_error(error)
    except (sqlite3.DatabaseError, OSError):
        return emit_error(
            ControlError(
                "STATE_FAIL_CLOSED",
                "local authority is unavailable or corrupt; writes stopped",
                exit_status=EXIT_STATE,
            )
        )
    except Exception:
        return emit_error(
            ControlError(
                "INTERNAL_FAIL_CLOSED",
                "control plane failed closed",
                exit_status=EXIT_STATE,
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
