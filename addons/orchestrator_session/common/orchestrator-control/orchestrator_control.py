#!/usr/bin/env python3
"""Transactional, local-only orchestrator control plane (Python stdlib only)."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit


INTERFACE_VERSION = "1.0"
SCHEMA_VERSION = "1.0"
EXIT_INVALID = 2
EXIT_CONFLICT = 3
EXIT_STATE = 4
MAX_JSON_BYTES = 1_048_576
MAX_TEXT = 50_000
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
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
    "CLOSING",
    "CLOSED",
    "ARCHIVE_PENDING",
    "ARCHIVED",
    "DUPLICATE_STOP",
    "FAILED",
    "SUPERSEDED",
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


def safe_state_dir(raw: str) -> Path:
    path = Path(raw).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
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
    if rule["schema_version"] != SCHEMA_VERSION:
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
        "schema_version": SCHEMA_VERSION,
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
    if ledger["schema_version"] != SCHEMA_VERSION:
        fail("VERSION_UNSUPPORTED", "policy ledger schema version is unsupported")
    rules = [validate_rule(item) for item in ledger["rules"]] if isinstance(ledger["rules"], list) else []
    if not rules:
        fail("SCHEMA_INVALID", "policy ledger requires rules")
    ids = [(rule["id"], rule["rule_revision"]) for rule in rules]
    if len(ids) != len(set(ids)):
        fail("SCHEMA_INVALID", "policy rule identity/revision must be unique")
    return {
        "schema_version": SCHEMA_VERSION,
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
                    connection.close()
                    fail(
                        "STATE_UNSAFE",
                        "SQLite authority files cannot be symlinks",
                        exit_status=EXIT_STATE,
                    )
                if (
                    hasattr(os, "getuid")
                    and state_file.stat().st_uid != os.getuid()
                ):
                    connection.close()
                    fail(
                        "STATE_OWNERSHIP",
                        "SQLite authority must be owned by the current user",
                        exit_status=EXIT_STATE,
                    )
                os.chmod(state_file, 0o600)
        finally:
            os.umask(previous_umask)
        return connection

    def initialize(self, now: str) -> dict[str, Any]:
        timestamp(now)
        if self.db_path.exists() and self.db_path.is_symlink():
            fail("STATE_UNSAFE", "database cannot be a symlink", exit_status=EXIT_STATE)
        created = not self.db_path.exists()
        connection = self.connect()
        try:
            connection.executescript(SCHEMA_SQL)
            os.chmod(self.db_path, 0o600)
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM metadata WHERE key='schema_version'").fetchone():
                major = connection.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()[0].split(".", 1)[0]
                if major != SCHEMA_VERSION.split(".", 1)[0]:
                    fail("VERSION_UNSUPPORTED", "database schema major version is unsupported")
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
                    "created_at": now,
                }
                connection.executemany(
                    "INSERT INTO metadata(key,value) VALUES(?,?)", values.items()
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"created": created, "schema_version": SCHEMA_VERSION}

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
            "heartbeat_protocol": {
                "command": "record-heartbeat",
                "requires_current_fence": True,
            },
            "closure_protocol": {
                "command": "record-handback",
                "archive_receipt_command": "record-archive-receipt",
                "requires_current_fence": True,
            },
            "receipt_required": {
                "task_id": request["task_id"],
                "policy_snapshot_revision": policy_revision,
                "applicable_rule_ids": rule_ids,
                "lease_epoch": lease_epoch,
                "fencing_token": fence,
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

    def classify(self, raw: Any) -> dict[str, Any]:
        request = validate_classify(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
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
                connection.commit()
                return {"task_id": request["task_id"], "state": "RUNNING"}
            task = self.checked_task(connection, request, {"LAUNCH_PENDING"})
            expected_ids = json.loads(task["applicable_rule_ids_json"])
            if sorted(request["applicable_rule_ids"]) != sorted(expected_ids):
                fail("RULE_RECEIPT_MISMATCH", "launch receipt omitted applicable rules")
            connection.execute(
                "UPDATE tasks SET state='RUNNING',external_thread_id=?,updated_at=? WHERE task_id=?",
                (request["external_thread_id"], request["now"], request["task_id"]),
            )
            connection.execute(
                "UPDATE launches SET receipt_json=? WHERE task_id=?",
                (canonical(request), request["task_id"]),
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
                {"external_thread_id": request["external_thread_id"]},
            )
            connection.commit()
            return {"task_id": request["task_id"], "state": "RUNNING"}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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

    def record_handback(self, raw: Any) -> dict[str, Any]:
        request = validate_handback(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
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
                    "disposition": request["disposition"],
                }
            )
            if existing:
                if existing["request_hash"] != request_hash:
                    fail("IDEMPOTENCY_CONFLICT", "handback_id input changed", exit_status=EXIT_CONFLICT)
                connection.commit()
                return json.loads(existing["result_json"])
            task = self.checked_task(connection, request, {"RUNNING", "BLOCKED", "FAILED"})
            before = task["state"]
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
            successor_result = None
            if request["successor_request"] is not None:
                connection.execute(
                    "UPDATE owner_claims SET status='released',heartbeat_at=? WHERE task_id=? AND status='active'",
                    (request["now"], request["task_id"]),
                )
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
            if request["successor_request"] is not None:
                connection.execute(
                    """UPDATE owner_claims SET status='released',heartbeat_at=?
                       WHERE task_id=? AND status='active'""",
                    (request["now"], request["task_id"]),
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
                "evidence_count": len(request["checks"]) + len(request["exact_refs"]),
                "resource_count": len(request["resources"]),
                "reclaimed_bytes": sum(
                    item.get("bytes", 0)
                    for item in request["resources"]
                    if item["disposition"] == "removed"
                ),
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
                        }
                    ),
                    canonical(result),
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

    def heartbeat(self, raw: Any) -> dict[str, Any]:
        request = validate_heartbeat(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            task = self.checked_task(connection, request, {"RUNNING", "BLOCKED"})
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
                {"lease_epoch": request["lease_epoch"]},
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

    def recycle(self, raw: Any) -> dict[str, Any]:
        request = validate_recycle(raw)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            blocked = connection.execute(
                "SELECT * FROM tasks WHERE state='BLOCKED' ORDER BY task_id"
            ).fetchall()
            expected = {row["task_id"] for row in blocked}
            provided = {item["task_id"] for item in request["audits"]}
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
            for audit in request["audits"]:
                row = rows[audit["task_id"]]
                block = {
                    **audit,
                    "audit_required": False,
                    "audited_at": request["now"],
                }
                if audit["outcome"] == "resume":
                    fanout = len(json.loads(row["dependencies_json"]))
                    resumable.append((row, fanout, block))
                elif audit["outcome"] == "archive":
                    connection.execute(
                        "UPDATE tasks SET state='ARCHIVED',block_json=?,updated_at=? WHERE task_id=?",
                        (canonical(block), request["now"], row["task_id"]),
                    )
                    connection.execute(
                        "UPDATE owner_claims SET status='released' WHERE task_id=?",
                        (row["task_id"],),
                    )
                    archived.append(row["task_id"])
                elif audit["outcome"] == "owner_gate":
                    connection.execute(
                        "UPDATE tasks SET block_json=?,updated_at=? WHERE task_id=?",
                        (canonical(block), request["now"], row["task_id"]),
                    )
                    owner_gated.append(row["task_id"])
                else:
                    connection.execute(
                        "UPDATE tasks SET block_json=?,updated_at=? WHERE task_id=?",
                        (canonical(block), request["now"], row["task_id"]),
                    )
            resumable.sort(key=lambda item: (-item[0]["priority"], -item[1], item[0]["created_at"], item[0]["task_id"]))
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
                        (request["now"], row["task_id"]),
                    )
                else:
                    connection.execute(
                        "UPDATE tasks SET block_json=?,updated_at=? WHERE task_id=?",
                        (canonical(block), request["now"], row["task_id"]),
                    )
            self.event(
                connection,
                request["now"],
                None,
                request["request_id"],
                "BLOCKED_QUEUE_RECYCLED",
                "AUDIT_COMMITTED",
                ["BR-BLOCK-001", "BR-CI-001"],
                "BLOCKED",
                "RUNNING" if ranked else "BLOCKED",
                {"ranked_task_ids": [item["task_id"] for item in ranked]},
            )
            connection.commit()
            return {
                "ranked_resumable": ranked,
                "selected_task_id": ranked[0]["task_id"] if ranked else None,
                "archived_task_ids": sorted(archived),
                "owner_gated_task_ids": sorted(owner_gated),
            }
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

    def status(self) -> dict[str, Any]:
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
                tasks.append(
                    {
                        "task_id": row["task_id"],
                        "state": row["state"],
                        "priority": row["priority"],
                        "repo_alias": target["remote"].split("/", 1)[1],
                        "path": target["path"],
                        "updated_at": row["updated_at"],
                        "block": block,
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
            return {
                "schema_version": self.metadata(connection, "schema_version"),
                "revision": int(self.metadata(connection, "revision")),
                "policy_revision": int(self.metadata(connection, "policy_revision")),
                "tasks": tasks,
                "rules": rules,
                "outbox": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT outbox_id,kind,task_id,state,attempts,created_at,updated_at FROM outbox ORDER BY created_at,outbox_id"
                    )
                ],
            }
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
        required |= {"external_thread_id", "applicable_rule_ids"}
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
    if request["disposition"] == "completed" and any(
        exact_refs[key] is None
        for key in ("candidate_sha", "pr_url", "merge_sha", "default_sha")
    ):
        fail(
            "HANDBACK_INCOMPLETE",
            "completed handback requires candidate, PR, merge, and default refs",
        )
    if (
        request["disposition"] == "completed"
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
    }
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


def validate_recycle(value: Any) -> dict[str, Any]:
    request = strict(value, {"interface_version", "request_id", "audits", "now"}, label="recycle request")
    if request["interface_version"] != INTERFACE_VERSION or not isinstance(request["audits"], list):
        fail("SCHEMA_INVALID", "recycle interface or audits is invalid")
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
    for item in request["audits"]:
        item = strict(item, {"task_id", "classification", "outcome", "reason_code", "evidence_refs"}, label="audit")
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
                "evidence_refs": string_list(item["evidence_refs"], "audit.evidence_refs"),
            }
        )
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": identifier(request["request_id"], "request_id"),
        "audits": audits,
        "now": timestamp(request["now"]),
    }


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
    return {**base, "lease_expires_at": expires}


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
    for name in (
        "record-policy-rule",
        "prepare-launch",
        "effective-rules",
        "classify-decision",
        "record-launch-receipt",
        "record-handback",
        "record-archive-receipt",
        "takeover-lease",
        "record-heartbeat",
        "recycle-queue",
        "migrate-decisions",
    ):
        command = commands.add_parser(name)
        command.add_argument("--request", required=True)
    commands.add_parser("status")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        state_dir = safe_state_dir(args.state_dir)
        ledger = Path(args.policy_ledger).resolve()
        plane = Plane(state_dir, ledger)
        operations: dict[str, tuple[Callable[[Any], Any], str]] = {
            "record-policy-rule": (plane.record_rule, "record-policy-rule"),
            "prepare-launch": (plane.prepare_launch, "prepare-launch"),
            "effective-rules": (plane.effective_rules, "effective-rules"),
            "classify-decision": (plane.classify, "classify-decision"),
            "record-launch-receipt": (plane.launch_receipt, "record-launch-receipt"),
            "record-handback": (plane.record_handback, "record-handback"),
            "record-archive-receipt": (plane.archive_receipt, "record-archive-receipt"),
            "takeover-lease": (plane.takeover_lease, "takeover-lease"),
            "record-heartbeat": (plane.heartbeat, "record-heartbeat"),
            "recycle-queue": (plane.recycle, "recycle-queue"),
            "migrate-decisions": (plane.migrate, "migrate-decisions"),
        }
        if args.command == "init":
            emit_success("init", plane.initialize(args.now))
        elif args.command == "status":
            emit_success("status", plane.status())
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
