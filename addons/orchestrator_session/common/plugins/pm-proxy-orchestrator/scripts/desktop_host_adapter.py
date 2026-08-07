#!/usr/bin/env python3
"""Opt-in Codex Desktop host adapter for one exact root-orchestrator task.

The adapter never changes global Codex configuration.  It launches a separate
Electron data directory, makes Desktop execute this file as its app-server
proxy, and answers hook identity queries for one exact root thread ID.  Every
other thread in that host is attested as a worker.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Mapping


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = Path(__file__).resolve()
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MCP_SERVER = PLUGIN_ROOT / "scripts" / "mcp_server.py"
PRE_HOOK = PLUGIN_ROOT / "hooks" / "pre_tool_use_root_guard.py"
POST_HOOK = PLUGIN_ROOT / "hooks" / "post_tool_use_lifecycle.py"
HOST_ATTESTATION = PLUGIN_ROOT / "hooks" / "host_attestation.py"
HOOKS_MANIFEST = PLUGIN_ROOT / "hooks" / "hooks.json"
INTERFACE_VERSION = "1.1"
PROOF_VERSION = "1.0"
SESSION_VERSION = "1.3"
BOOTSTRAP_GRANT_VERSION = "1.0"
BOOTSTRAP_GRANT_MAX_TTL_SECONDS = 300
PROOF_TTL_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_JSON_BYTES = 2_000_000
MAX_ATTESTATION_BYTES = 4096
OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
NONCE = re.compile(r"^[0-9a-f]{32}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLUGIN_ID = "pm-proxy-orchestrator@project-firestarter"
MCP_SERVER_ID = "pm-proxy-orchestrator"
REQUIRED_TOOLS = {
    "pm_proxy_acknowledge_control_schema_hold",
    "pm_proxy_close_and_refill",
    "pm_proxy_configure_capacity",
    "pm_proxy_doctor",
    "pm_proxy_heartbeat",
    "pm_proxy_lifecycle_watchdog",
    "pm_proxy_prepare_launch",
    "pm_proxy_record_archive_receipt",
    "pm_proxy_reconcile_legacy_archive",
    "pm_proxy_record_launch_receipt",
    "pm_proxy_record_refill_receipt",
    "pm_proxy_record_setup_failure",
    "pm_proxy_route_owner_decision",
    "pm_proxy_reconcile_expired_lease",
    "pm_proxy_slot_status",
    "pm_proxy_status",
    "pm_proxy_verify_runtime",
    "pm_proxy_watchdog_refill",
}
PROMPT_FREE_CONTROL_TOOLS = (
    "pm_proxy_acknowledge_control_schema_hold",
    "pm_proxy_close_and_refill",
    "pm_proxy_configure_capacity",
    "pm_proxy_doctor",
    "pm_proxy_heartbeat",
    "pm_proxy_lifecycle_watchdog",
    "pm_proxy_prepare_launch",
    "pm_proxy_record_archive_receipt",
    "pm_proxy_reconcile_legacy_archive",
    "pm_proxy_record_launch_receipt",
    "pm_proxy_record_refill_receipt",
    "pm_proxy_record_setup_failure",
    "pm_proxy_route_owner_decision",
    "pm_proxy_slot_status",
    "pm_proxy_status",
    "pm_proxy_verify_runtime",
    "pm_proxy_watchdog_refill",
)
ADOPTION_REQUIRED_TRUE = {
    "archive_refill_fence_verified",
    "hosted_paths_uncovered",
    "lifecycle_debt_clear_verified",
    "no_side_effect_canary_verified",
    "pre_tool_denial_verified",
    "reserved_create_admission_verified",
    "typed_mcp_control_verified",
}
DENIAL_MARKER = "ROOT_ORCHESTRATOR_TASK_DOMAIN_DENIED:Bash"
SESSION_ENV = "ORC_DESKTOP_HOST_SESSION"
TOKEN_ENV = "ORC_DESKTOP_HOST_TOKEN"
SOCKET_ENV = "ORC_DESKTOP_HOST_SOCKET"
INSTANCE_ENV = "ORC_DESKTOP_HOST_INSTANCE_ID"
BOOTSTRAP_GRANT_ENV = "ORC_DESKTOP_BOOTSTRAP_RECOVERY_GRANT"
REAL_CODEX_ENV = "ORC_DESKTOP_REAL_CODEX"
ADAPTER_ENV_VARS = {
    SESSION_ENV,
    TOKEN_ENV,
    SOCKET_ENV,
    INSTANCE_ENV,
    BOOTSTRAP_GRANT_ENV,
    REAL_CODEX_ENV,
    "CODEX_CLI_PATH",
    "CODEX_APP_SERVER_FORCE_CLI",
    "CODEX_ELECTRON_USER_DATA_PATH",
}
USER_DATA_SWITCH = "--user-data-dir="


class AdapterError(RuntimeError):
    """A bounded host-adapter safety check failed."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: Any) -> dt.datetime:
    if not isinstance(value, str) or UTC.fullmatch(value) is None:
        raise AdapterError("timestamp-invalid")
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )


def strict_json(raw: str, *, maximum: int = MAX_JSON_BYTES) -> Any:
    def no_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AdapterError("duplicate-json-key")
            result[key] = value
        return result

    if len(raw.encode("utf-8")) > maximum:
        raise AdapterError("json-too-large")
    try:
        return json.loads(raw, object_pairs_hook=no_duplicate)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AdapterError("json-invalid") from exc


def exact_keys(
    value: Mapping[str, Any], allowed: set[str], required: set[str]
) -> None:
    if set(value) - allowed or not required.issubset(value):
        raise AdapterError("fields-invalid")


def canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def secure_file(path: Path, *, executable: bool = False) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise AdapterError("file-path-invalid")
    try:
        resolved = path.resolve(strict=True)
        metadata = path.stat()
    except OSError as exc:
        raise AdapterError("file-missing") from exc
    if (
        resolved != path
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid not in {0, os.getuid()}
        or metadata.st_mode & 0o022
        or (executable and not os.access(path, os.X_OK))
    ):
        raise AdapterError("file-security-invalid")
    return resolved


def ensure_private_dir(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise AdapterError("private-dir-invalid")
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        metadata = path.stat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AdapterError("private-dir-invalid") from exc
    if (
        resolved != path
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or (metadata.st_mode & 0o077) != 0
    ):
        raise AdapterError("private-dir-not-private")
    return path


def existing_private_dir(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise AdapterError("private-dir-invalid")
    try:
        metadata = path.stat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AdapterError("private-dir-invalid") from exc
    if (
        resolved != path
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or (metadata.st_mode & 0o077) != 0
    ):
        raise AdapterError("private-dir-not-private")
    return path


def short_socket_path(instance_id: str, token: str) -> Path:
    temporary_root = Path("/private/tmp")
    if not temporary_root.is_dir():
        temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
    socket_root = ensure_private_dir(
        temporary_root / f"orc-desktop-host-{os.getuid()}"
    )
    suffix = hashlib.sha256(
        f"{instance_id}\0{token}".encode("utf-8")
    ).hexdigest()[:16]
    path = socket_root / f"attestation-{suffix}.sock"
    if len(os.fsencode(path)) > 100:
        raise AdapterError("socket-path-too-long")
    return path


def read_private_json(path: Path) -> dict[str, Any]:
    try:
        if (
            not path.is_absolute()
            or path.is_symlink()
            or not path.is_file()
            or path.resolve(strict=True) != path
            or existing_private_dir(path.parent) != path.parent
            or (path.stat().st_mode & 0o777) != 0o600
            or path.stat().st_uid != os.getuid()
        ):
            raise AdapterError("private-json-invalid")
        value = strict_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise AdapterError("private-json-invalid") from exc
    if not isinstance(value, dict):
        raise AdapterError("private-json-invalid")
    return value


def atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
    directory = ensure_private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


@contextlib.contextmanager
def session_lock(instance_dir: Path) -> Iterator[None]:
    directory = ensure_private_dir(instance_dir)
    path = directory / ".session.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or (metadata.st_mode & 0o777) != 0o600:
            raise AdapterError("session-lock-invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def manifest() -> dict[str, Any]:
    secure_file(MANIFEST_PATH)
    value = strict_json(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("name") != "pm-proxy-orchestrator":
        raise AdapterError("plugin-manifest-invalid")
    version = value.get("version")
    if not isinstance(version, str) or OPAQUE.fullmatch(version) is None:
        raise AdapterError("plugin-version-invalid")
    return value


def hook_bundle_digest() -> str:
    bundle = hashlib.sha256()
    for path in (HOST_ATTESTATION, HOOKS_MANIFEST, POST_HOOK, PRE_HOOK):
        secure_file(path)
        bundle.update(path.relative_to(PLUGIN_ROOT).as_posix().encode("utf-8"))
        bundle.update(b"\0")
        bundle.update(bytes.fromhex(digest(path)))
    return bundle.hexdigest()


def secure_plugin_dir(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise AdapterError("plugin-directory-invalid")
    try:
        resolved = path.resolve(strict=True)
        metadata = path.stat()
    except OSError as exc:
        raise AdapterError("plugin-directory-invalid") from exc
    if (
        resolved != path
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
    ):
        raise AdapterError("plugin-directory-invalid")
    return path


def plugin_tree_digest(root: Path) -> str:
    directory = secure_plugin_dir(root)
    tree = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise AdapterError("plugin-tree-symlink-denied")
        if not path.is_file():
            continue
        secured = secure_file(path)
        executable = bool(
            secured.stat().st_mode
            & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        )
        tree.update(relative.as_posix().encode("utf-8"))
        tree.update(b"\0x\0" if executable else b"\0-\0")
        tree.update(bytes.fromhex(digest(secured)))
    return tree.hexdigest()


def source_plugin_root(project: Path) -> Path:
    candidates = (
        project / "pm-proxy-orchestrator",
        project
        / "addons"
        / "orchestrator_session"
        / "common"
        / "plugins"
        / "pm-proxy-orchestrator",
    )
    matches = [
        path for path in candidates if path.is_dir() and not path.is_symlink()
    ]
    if len(matches) != 1:
        raise AdapterError("bootstrap-plugin-path-invalid")
    return secure_plugin_dir(matches[0].resolve(strict=True))


def probe_hook() -> None:
    event = {
        "hook_event_name": "PreToolUse",
        "session_id": "synthetic-adapter-preflight",
        "tool_name": "Bash",
        "tool_input": {"command": "/usr/bin/true"},
        "tool_use_id": "synthetic-adapter-preflight",
    }
    environment = dict(os.environ)
    environment.pop(SOCKET_ENV, None)
    environment["ROOT_ORCHESTRATOR_ROLE"] = "trusted-project-hook"
    completed = subprocess.run(
        [sys.executable, str(PRE_HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
        env=environment,
    )
    if completed.returncode != 0 or DENIAL_MARKER not in completed.stdout:
        raise AdapterError("direct-hook-canary-failed")


def installed_plugin(codex_cli: Path, expected_version: str) -> None:
    environment = dict(os.environ)
    for name in ADAPTER_ENV_VARS:
        environment.pop(name, None)
    environment.pop("ROOT_ORCHESTRATOR_ROLE", None)
    completed = subprocess.run(
        [str(codex_cli), "plugin", "list", "--json"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env=environment,
    )
    if completed.returncode != 0 or completed.stderr:
        raise AdapterError("installed-plugin-query-failed")
    value = strict_json(completed.stdout)
    installed = value.get("installed") if isinstance(value, dict) else None
    if not isinstance(installed, list):
        raise AdapterError("installed-plugin-query-invalid")
    matches = [
        item
        for item in installed
        if isinstance(item, dict)
        and item.get("pluginId")
        == "pm-proxy-orchestrator@project-firestarter"
    ]
    source = matches[0].get("source") if len(matches) == 1 else None
    source_path = source.get("path") if isinstance(source, dict) else None
    try:
        source_matches = (
            isinstance(source, dict)
            and source.get("source") == "local"
            and isinstance(source_path, str)
            and Path(source_path).is_absolute()
            and not Path(source_path).is_symlink()
            and Path(source_path).resolve(strict=True) == PLUGIN_ROOT
        )
    except OSError:
        source_matches = False
    if (
        len(matches) != 1
        or matches[0].get("installed") is not True
        or matches[0].get("enabled") is not True
        or matches[0].get("version") != expected_version
        or not source_matches
    ):
        raise AdapterError("installed-plugin-version-mismatch")
    assert isinstance(source_path, str)
    source_root = secure_plugin_dir(Path(source_path))
    cache_root = secure_plugin_dir(
        Path.home()
        / ".codex/plugins/cache/project-firestarter/pm-proxy-orchestrator"
        / expected_version
    )
    if PLUGIN_ROOT not in {source_root, cache_root}:
        raise AdapterError("adapter-not-from-installed-plugin")
    if plugin_tree_digest(source_root) != plugin_tree_digest(cache_root):
        raise AdapterError("installed-plugin-cache-mismatch")


def approval_grant_arguments() -> list[str]:
    """Return only exact per-tool overrides for the isolated ORC app-server."""

    result: list[str] = []
    for tool in PROMPT_FREE_CONTROL_TOOLS:
        key = (
            f'plugins."{PLUGIN_ID}".mcp_servers."{MCP_SERVER_ID}".'
            f'tools."{tool}".approval_mode="approve"'
        )
        result.extend(("-c", key))
    return result


def approval_grant_digest() -> str:
    encoded = json.dumps(
        approval_grant_arguments(), separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def isolated_app_server_arguments(
    arguments: list[str], *, grant_enabled: bool = True
) -> list[str]:
    """Place the exact grant after host config and before the app-server verb."""

    if not app_server_argv(arguments):
        raise AdapterError("only-foreground-app-server-is-allowed")
    if not grant_enabled:
        return list(arguments)
    index = arguments.index("app-server")
    return [
        *arguments[:index],
        *approval_grant_arguments(),
        *arguments[index:],
    ]


def mcp_doctor(state_dir: Path) -> tuple[str, dict[str, Any]]:
    state_dir = existing_private_dir(state_dir)
    secure_file(MCP_SERVER)
    messages = [
        {"jsonrpc": "2.0", "id": "initialize", "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": "list", "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": "doctor",
            "method": "tools/call",
            "params": {
                "name": "pm_proxy_doctor",
                "arguments": {"state_dir": str(state_dir)},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "status",
            "method": "tools/call",
            "params": {
                "name": "pm_proxy_status",
                "arguments": {"state_dir": str(state_dir)},
            },
        },
    ]
    completed = subprocess.run(
        [sys.executable, str(MCP_SERVER)],
        input="".join(json.dumps(item, separators=(",", ":")) + "\n" for item in messages),
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
        env={
            "HOME": str(Path.home()),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    if completed.returncode != 0 or completed.stderr:
        raise AdapterError("typed-doctor-failed")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 4:
        raise AdapterError("typed-doctor-invalid")
    responses = [strict_json(line) for line in lines]
    if not all(isinstance(item, dict) for item in responses):
        raise AdapterError("typed-doctor-invalid")
    initialized, listed, doctor, status = responses
    server = initialized.get("result", {}).get("serverInfo", {})
    version = server.get("version")
    tools = listed.get("result", {}).get("tools")
    if (
        not isinstance(version, str)
        or not isinstance(tools, list)
        or {item.get("name") for item in tools if isinstance(item, dict)}
        != REQUIRED_TOOLS
    ):
        raise AdapterError("typed-mcp-surface-invalid")
    wrapped = doctor.get("result", {})
    structured = wrapped.get("structuredContent") if isinstance(wrapped, dict) else None
    if not isinstance(structured, dict) or structured.get("ok") is not True:
        raise AdapterError("typed-doctor-denied")
    result = structured.get("result")
    pin = result.get("runtime_pin") if isinstance(result, dict) else None
    if not isinstance(pin, dict) or pin.get("verified") is not True:
        raise AdapterError("runtime-pin-not-verified")
    status_wrapped = status.get("result", {})
    status_structured = (
        status_wrapped.get("structuredContent")
        if isinstance(status_wrapped, dict)
        else None
    )
    status_result = (
        status_structured.get("result")
        if isinstance(status_structured, dict)
        and status_structured.get("ok") is True
        else None
    )
    lifecycle = (
        status_result.get("lifecycle_watchdog")
        if isinstance(status_result, dict)
        else None
    )
    safety = (
        status_result.get("operational_safety")
        if isinstance(status_result, dict)
        else None
    )
    if not isinstance(lifecycle, dict) or not isinstance(safety, dict):
        raise AdapterError("typed-status-invalid")
    adoption = lifecycle.get("dispatcher_adoption")
    if adoption is not None and not isinstance(adoption, dict):
        raise AdapterError("typed-status-invalid")
    proofs: dict[str, Any] | None = None
    if isinstance(adoption, dict):
        exact_keys(
            adoption,
            {
                "adoption_mode",
                "covered_path_dispatcher_enforcement",
                "plugin_version",
                "proofs",
                "recorded_at",
                "request_id",
                "universal_dispatcher_enforcement",
            },
            {
                "adoption_mode",
                "covered_path_dispatcher_enforcement",
                "plugin_version",
                "proofs",
                "recorded_at",
                "request_id",
                "universal_dispatcher_enforcement",
            },
        )
        value = adoption.get("proofs")
        if not isinstance(value, dict):
            raise AdapterError("typed-status-invalid")
        exact_keys(
            value,
            ADOPTION_REQUIRED_TRUE | {"universal_coverage_claimed"},
            ADOPTION_REQUIRED_TRUE | {"universal_coverage_claimed"},
        )
        proofs = value
    safety_required_true = {
        "automatic_launch_refill_allowed",
        "covered_path_automatic_launch_refill_allowed",
        "covered_path_dispatcher_enforcement",
        "dispatcher_adoption_version_matches",
        "runtime_pin_verified",
    }
    safety_required_false = {
        "platform_dispatcher_enforcement",
        "unattended_automatic_launch_refill_allowed",
        "universal_dispatcher_enforcement",
    }
    grant_verified = bool(
        isinstance(adoption, dict)
        and isinstance(proofs, dict)
        and adoption.get("adoption_mode") == "COVERED_PATH_GUARDRAIL"
        and adoption.get("plugin_version") == version
        and adoption.get("covered_path_dispatcher_enforcement") is True
        and adoption.get("universal_dispatcher_enforcement") is False
        and all(proofs.get(key) is True for key in ADOPTION_REQUIRED_TRUE)
        and proofs.get("universal_coverage_claimed") is False
        and all(safety.get(key) is True for key in safety_required_true)
        and all(safety.get(key) is False for key in safety_required_false)
        and safety.get("automatic_launch_refill_scope") == "COVERED_PATH_ONLY"
    )
    bound_pin = dict(pin)
    for key in ("revision", "policy_revision"):
        if isinstance(status_result.get(key), bool) or not isinstance(
            status_result.get(key), int
        ):
            raise AdapterError("typed-status-invalid")
    worker_capacity = status_result.get("worker_capacity")
    if (
        not isinstance(worker_capacity, dict)
        or isinstance(worker_capacity.get("configured_capacity"), bool)
        or not isinstance(worker_capacity.get("configured_capacity"), int)
    ):
        raise AdapterError("typed-status-invalid")
    bound_pin["state_revision"] = status_result["revision"]
    bound_pin["policy_revision"] = status_result["policy_revision"]
    bound_pin["configured_capacity"] = worker_capacity[
        "configured_capacity"
    ]
    bound_pin["prompt_free_control_grant_verified"] = grant_verified
    bound_pin["dispatcher_adoption_sha256"] = (
        hashlib.sha256(
            json.dumps(adoption, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if grant_verified
        else None
    )
    return version, bound_pin


def live_hook_canary(codex_cli: Path, instance_dir: Path, timeout: int) -> str:
    with tempfile.TemporaryDirectory(prefix=".live-canary-", dir=instance_dir) as raw:
        project = Path(raw)
        os.chmod(project, 0o700)
        marker = project / "denied-exec-marker"
        subprocess.run(
            ["git", "init", "--quiet", str(project)],
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
        )
        prompt = (
            "This is a synthetic hook canary. Use Bash exactly once to execute "
            f"/usr/bin/touch {marker}. Do not call any other tool. If the call is "
            "denied, stop."
        )
        environment = dict(os.environ)
        for name in ADAPTER_ENV_VARS:
            environment.pop(name, None)
        environment["ROOT_ORCHESTRATOR_ROLE"] = "trusted-project-hook"
        completed = subprocess.run(
            [
                str(codex_cli),
                "--enable",
                "hooks",
                "-a",
                "never",
                "-C",
                str(project),
                "exec",
                "--ephemeral",
                "--json",
                prompt,
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=environment,
        )
        combined = completed.stdout + "\n" + completed.stderr
        if marker.exists() or DENIAL_MARKER not in combined:
            raise AdapterError("live-hook-canary-failed")
        return DENIAL_MARKER


def proof_material(
    *, codex_cli: Path, state_dir: Path, version: str, pin: dict[str, Any]
) -> dict[str, Any]:
    return {
        "adapter_sha256": digest(ADAPTER_PATH),
        "codex_cli": str(codex_cli),
        "codex_cli_sha256": digest(codex_cli),
        "dispatcher_adoption_sha256": pin.get("dispatcher_adoption_sha256"),
        "hook_bundle_sha256": hook_bundle_digest(),
        "plugin_version": version,
        "prompt_free_control_grant_verified": pin.get(
            "prompt_free_control_grant_verified"
        ),
        "runtime_sha256": pin.get("runtime_sha256"),
        "state_dir": str(state_dir),
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    instance_dir = ensure_private_dir(Path(args.instance_dir))
    state_dir = existing_private_dir(Path(args.state_dir))
    codex_cli = secure_file(Path(args.codex_cli), executable=True)
    current_manifest = manifest()
    installed_plugin(codex_cli, current_manifest["version"])
    probe_hook()
    server_version, pin = mcp_doctor(state_dir)
    if server_version != current_manifest["version"]:
        raise AdapterError("plugin-version-mismatch")
    denial = live_hook_canary(codex_cli, instance_dir, args.timeout)
    now = utc_now()
    proof = {
        "proof_version": PROOF_VERSION,
        **proof_material(
            codex_cli=codex_cli,
            state_dir=state_dir,
            version=server_version,
            pin=pin,
        ),
        "denial_reason": denial,
        "verified_at": iso(now),
        "valid_until": iso(now + dt.timedelta(seconds=PROOF_TTL_SECONDS)),
    }
    atomic_private_json(instance_dir / "live-proof.json", proof)
    return {
        "ok": True,
        "result": {
            "proof": "VERIFIED",
            "plugin_version": server_version,
            "prompt_free_control_grant_verified": pin.get(
                "prompt_free_control_grant_verified"
            )
            is True,
            "runtime_pin_verified": True,
            "valid_until": proof["valid_until"],
        },
    }


def validate_proof(
    instance_dir: Path, codex_cli: Path, state_dir: Path, version: str, pin: dict[str, Any]
) -> dict[str, Any]:
    proof_path = instance_dir / "live-proof.json"
    proof = read_private_json(proof_path)
    expected = proof_material(
        codex_cli=codex_cli,
        state_dir=state_dir,
        version=version,
        pin=pin,
    )
    exact_keys(
        proof,
        {
            "adapter_sha256",
            "codex_cli",
            "codex_cli_sha256",
            "denial_reason",
            "dispatcher_adoption_sha256",
            "hook_bundle_sha256",
            "plugin_version",
            "prompt_free_control_grant_verified",
            "proof_version",
            "runtime_sha256",
            "state_dir",
            "valid_until",
            "verified_at",
        },
        {
            "adapter_sha256",
            "codex_cli",
            "codex_cli_sha256",
            "denial_reason",
            "dispatcher_adoption_sha256",
            "hook_bundle_sha256",
            "plugin_version",
            "prompt_free_control_grant_verified",
            "proof_version",
            "runtime_sha256",
            "state_dir",
            "valid_until",
            "verified_at",
        },
    )
    if (
        proof.get("proof_version") != PROOF_VERSION
        or proof.get("denial_reason") != DENIAL_MARKER
        or any(proof.get(key) != value for key, value in expected.items())
        or parse_utc(proof.get("verified_at")) > utc_now()
        or parse_utc(proof.get("valid_until")) < utc_now()
    ):
        raise AdapterError("live-proof-stale-or-mismatched")
    return proof


def git_output(project: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project), *arguments],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError("bootstrap-source-git-invalid") from exc
    if completed.returncode != 0 or completed.stderr.strip():
        raise AdapterError("bootstrap-source-git-invalid")
    return completed.stdout.strip()


def bootstrap_grant_fields() -> set[str]:
    return {
        "authorization_request_id", "base_sha", "binding_sha256",
        "configured_capacity", "decision", "decision_id",
        "decision_request_id", "expected_state_revision", "expires_at",
        "external_thread_id", "fencing_token", "grant_id", "grant_version",
        "instance_dir", "instance_id", "issued_at", "lease_epoch",
        "max_uses", "operation", "plugin_root", "plugin_tree_sha256",
        "plugin_version", "policy_snapshot_revision", "policy_revision",
        "project_root", "request_id", "replay_target", "root_thread_id",
        "runtime_sha256", "source_commit_sha", "state_dir", "task_id",
        "ticket_id",
    }


def validate_bootstrap_recovery_grant(
    path: Path,
    *,
    instance_id: str,
    instance_dir: Path,
    root_thread_id: str,
    state_dir: Path,
    version: str,
    pin: Mapping[str, Any],
) -> dict[str, Any]:
    grant = read_private_json(path)
    fields = bootstrap_grant_fields()
    exact_keys(grant, fields, fields)
    unsigned = {key: value for key, value in grant.items() if key != "binding_sha256"}
    issued_at = parse_utc(grant.get("issued_at"))
    expires_at = parse_utc(grant.get("expires_at"))
    now = utc_now()
    project_root = Path(str(pin.get("project_root")))
    source_plugin = source_plugin_root(project_root)
    if (
        grant.get("grant_version") != BOOTSTRAP_GRANT_VERSION
        or grant.get("operation") != "pm_proxy_acknowledge_control_schema_hold"
        or grant.get("decision") != "CONTROL_SCHEMA_DEFECT_NO_TRUTHFUL_TERMINAL_ROUTE"
        or grant.get("replay_target") != "completed_local_only"
        or grant.get("max_uses") != 1
        or issued_at > now
        or expires_at < now
        or (expires_at - issued_at).total_seconds() > BOOTSTRAP_GRANT_MAX_TTL_SECONDS
        or path.parent != instance_dir
        or grant.get("instance_id") != instance_id
        or grant.get("instance_dir") != str(instance_dir)
        or grant.get("root_thread_id") != root_thread_id
        or grant.get("state_dir") != str(state_dir)
        or grant.get("project_root") != str(project_root)
        or grant.get("plugin_root") != str(source_plugin)
        or grant.get("plugin_version") != version
        or grant.get("plugin_tree_sha256") != plugin_tree_digest(source_plugin)
        or grant.get("plugin_tree_sha256") != plugin_tree_digest(PLUGIN_ROOT)
        or grant.get("runtime_sha256") != pin.get("runtime_sha256")
        or grant.get("expected_state_revision") != pin.get("state_revision")
        or grant.get("policy_revision") != pin.get("policy_revision")
        or grant.get("configured_capacity") != pin.get("configured_capacity")
        or grant.get("binding_sha256") != canonical_sha256(unsigned)
    ):
        raise AdapterError("bootstrap-grant-stale-or-mismatched")
    opaque_fields = {
        "authorization_request_id", "decision_id", "decision_request_id",
        "external_thread_id", "grant_id", "instance_id", "root_thread_id",
        "task_id", "ticket_id",
    }
    if any(
        not isinstance(grant.get(key), str)
        or OPAQUE.fullmatch(str(grant.get(key))) is None
        for key in opaque_fields
    ):
        raise AdapterError("bootstrap-grant-stale-or-mismatched")
    if any(
        isinstance(grant.get(key), bool) or not isinstance(grant.get(key), int)
        for key in (
            "configured_capacity", "expected_state_revision", "fencing_token",
            "lease_epoch", "max_uses", "policy_revision",
            "policy_snapshot_revision",
        )
    ):
        raise AdapterError("bootstrap-grant-stale-or-mismatched")
    for key in ("base_sha", "source_commit_sha"):
        if not isinstance(grant.get(key), str) or re.fullmatch(
            r"[0-9a-f]{40}", str(grant.get(key))
        ) is None:
            raise AdapterError("bootstrap-grant-stale-or-mismatched")
    return grant


def issue_bootstrap_recovery_grant(args: argparse.Namespace) -> dict[str, Any]:
    if (
        OPAQUE.fullmatch(args.instance_id) is None
        or OPAQUE.fullmatch(args.root_thread_id) is None
        or OPAQUE.fullmatch(args.grant_id) is None
    ):
        raise AdapterError("bootstrap-grant-identity-invalid")
    instance_dir = ensure_private_dir(Path(args.instance_dir))
    state_dir = existing_private_dir(Path(args.state_dir))
    codex_cli = secure_file(Path(args.codex_cli), executable=True)
    project_root = Path(args.project_root)
    if (
        not project_root.is_absolute()
        or project_root.is_symlink()
        or project_root.resolve(strict=True) != project_root
    ):
        raise AdapterError("bootstrap-source-path-invalid")
    current_manifest = manifest()
    installed_plugin(codex_cli, current_manifest["version"])
    version, pin = mcp_doctor(state_dir)
    if version != current_manifest["version"] or pin.get("project_root") != str(project_root):
        raise AdapterError("bootstrap-source-path-invalid")
    source_plugin = source_plugin_root(project_root)
    source_plugin_digest = plugin_tree_digest(source_plugin)
    if source_plugin_digest != plugin_tree_digest(PLUGIN_ROOT):
        raise AdapterError("bootstrap-plugin-tree-invalid")
    validate_proof(instance_dir, codex_cli, state_dir, version, pin)
    if git_output(project_root, "status", "--porcelain"):
        raise AdapterError("bootstrap-source-not-clean")
    base_sha = args.base_sha
    if re.fullmatch(r"[0-9a-f]{40}", base_sha) is None:
        raise AdapterError("bootstrap-source-base-invalid")
    source_commit_sha = git_output(project_root, "rev-parse", "HEAD")
    origin_master = git_output(project_root, "rev-parse", "refs/remotes/origin/master")
    if origin_master != base_sha:
        raise AdapterError("bootstrap-source-base-invalid")
    ancestor = subprocess.run(
        ["git", "-C", str(project_root), "merge-base", "--is-ancestor", base_sha, source_commit_sha],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if ancestor.returncode != 0:
        raise AdapterError("bootstrap-source-base-invalid")
    expected = {
        "state_revision": args.expected_state_revision,
        "policy_revision": args.expected_policy_revision,
        "configured_capacity": args.expected_configured_capacity,
    }
    if any(pin.get(key) != value for key, value in expected.items()):
        raise AdapterError("bootstrap-state-binding-mismatch")
    now = utc_now()
    lifetime = args.lifetime_seconds
    if lifetime < 1 or lifetime > BOOTSTRAP_GRANT_MAX_TTL_SECONDS:
        raise AdapterError("bootstrap-grant-lifetime-invalid")
    grant = {
        "authorization_request_id": args.authorization_request_id,
        "base_sha": base_sha,
        "configured_capacity": args.expected_configured_capacity,
        "decision": "CONTROL_SCHEMA_DEFECT_NO_TRUTHFUL_TERMINAL_ROUTE",
        "decision_id": args.decision_id,
        "decision_request_id": args.decision_request_id,
        "expected_state_revision": args.expected_state_revision,
        "expires_at": iso(now + dt.timedelta(seconds=lifetime)),
        "external_thread_id": args.external_thread_id,
        "fencing_token": args.fencing_token,
        "grant_id": args.grant_id,
        "grant_version": BOOTSTRAP_GRANT_VERSION,
        "instance_dir": str(instance_dir),
        "instance_id": args.instance_id,
        "issued_at": iso(now),
        "lease_epoch": args.lease_epoch,
        "max_uses": 1,
        "operation": "pm_proxy_acknowledge_control_schema_hold",
        "plugin_root": str(source_plugin),
        "plugin_tree_sha256": source_plugin_digest,
        "plugin_version": version,
        "policy_snapshot_revision": args.policy_snapshot_revision,
        "policy_revision": args.expected_policy_revision,
        "project_root": str(project_root),
        "request_id": args.request_id,
        "replay_target": "completed_local_only",
        "root_thread_id": args.root_thread_id,
        "runtime_sha256": pin["runtime_sha256"],
        "source_commit_sha": source_commit_sha,
        "state_dir": str(state_dir),
        "task_id": args.task_id,
        "ticket_id": args.ticket_id,
    }
    opaque_values = (
        args.authorization_request_id, args.decision_id,
        args.decision_request_id, args.external_thread_id, args.request_id,
        args.task_id, args.ticket_id,
    )
    if any(OPAQUE.fullmatch(value) is None for value in opaque_values):
        raise AdapterError("bootstrap-grant-identity-invalid")
    grant["binding_sha256"] = canonical_sha256(grant)
    grant_path = instance_dir / f"bootstrap-recovery-grant-{args.grant_id}.json"
    if grant_path.exists() or grant_path.is_symlink():
        raise AdapterError("bootstrap-grant-already-exists")
    atomic_private_json(grant_path, grant)
    return {
        "ok": True,
        "result": {
            "binding_sha256": grant["binding_sha256"],
            "expires_at": grant["expires_at"],
            "grant_id": grant["grant_id"],
            "grant_path": str(grant_path),
            "max_uses": 1,
            "plugin_tree_sha256": grant["plugin_tree_sha256"],
            "source_commit_sha": source_commit_sha,
            "status": "ISSUED",
        },
    }


def process_command(pid: Any) -> str | None:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return None
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def command_has_argument(command: str, argument: str) -> bool:
    """Match one exact ps-rendered argument without accepting prefix collisions."""

    if not command or not argument:
        return False
    return (
        command == argument
        or command.startswith(argument + " ")
        or command.endswith(" " + argument)
        or f" {argument} " in command
    )


def process_matches(pid: Any, *arguments: Any) -> bool:
    if not arguments or any(not isinstance(item, str) or not item for item in arguments):
        return False
    command = process_command(pid)
    return bool(command and all(command_has_argument(command, item) for item in arguments))


def desktop_process_matches(session: Mapping[str, Any]) -> bool:
    return process_matches(
        session.get("desktop_pid"),
        session.get("desktop_executable"),
        session.get("desktop_isolation_argument"),
    )


def desktop_launch_command(
    desktop: Path, electron_data_dir: Path, project: Path | None = None
) -> list[str]:
    """Build the argv that Electron sees before its single-instance decision."""

    command = [str(desktop), f"{USER_DATA_SWITCH}{electron_data_dir}"]
    if project is not None:
        command.append(str(project))
    return command


def wait_for_proxy(session_path: Path, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = read_private_json(session_path)
        desktop_alive = desktop_process_matches(session)
        if not desktop_alive:
            return False
        codex_cli = session.get("codex_cli")
        if (
            process_matches(session.get("proxy_pid"), str(ADAPTER_PATH), "app-server")
            and isinstance(codex_cli, str)
            and process_matches(session.get("app_server_pid"), codex_cli, "app-server")
        ):
            return True
        time.sleep(0.1)
    return False


def disarm_session(instance_dir: Path, session_path: Path) -> None:
    with session_lock(instance_dir):
        session = read_private_json(session_path)
        session["armed"] = False
        atomic_private_json(session_path, session)


def launch(args: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get("ROOT_ORCHESTRATOR_ROLE", "").strip():
        raise AdapterError("global-root-role-must-be-unset")
    private_host_environment = {
        SESSION_ENV,
        TOKEN_ENV,
        SOCKET_ENV,
        INSTANCE_ENV,
        REAL_CODEX_ENV,
        BOOTSTRAP_GRANT_ENV,
    }
    if any(os.environ.get(name, "").strip() for name in private_host_environment):
        raise AdapterError("host-adapter-environment-must-be-unset")
    if OPAQUE.fullmatch(args.instance_id) is None or OPAQUE.fullmatch(args.root_thread_id) is None:
        raise AdapterError("instance-or-root-id-invalid")
    instance_dir = ensure_private_dir(Path(args.instance_dir))
    state_dir = existing_private_dir(Path(args.state_dir))
    codex_cli = secure_file(Path(args.codex_cli), executable=True)
    desktop = secure_file(Path(args.desktop_executable), executable=True)
    current_manifest = manifest()
    installed_plugin(codex_cli, current_manifest["version"])
    probe_hook()
    server_version, pin = mcp_doctor(state_dir)
    if server_version != current_manifest["version"]:
        raise AdapterError("plugin-version-mismatch")
    proof = validate_proof(instance_dir, codex_cli, state_dir, server_version, pin)
    adoption_sha256 = pin.get("dispatcher_adoption_sha256")
    grant_enabled = pin.get("prompt_free_control_grant_verified") is True
    if grant_enabled and (
        not isinstance(adoption_sha256, str)
        or SHA256.fullmatch(adoption_sha256) is None
    ):
        raise AdapterError("covered-path-adoption-not-verified")
    if not grant_enabled and adoption_sha256 is not None:
        raise AdapterError("covered-path-adoption-not-verified")
    bootstrap_grant: dict[str, Any] | None = None
    bootstrap_grant_path: Path | None = None
    requested_bootstrap_grant = getattr(args, "bootstrap_grant", None)
    if requested_bootstrap_grant is not None:
        if not grant_enabled:
            raise AdapterError("bootstrap-grant-requires-covered-path-adoption")
        bootstrap_grant_path = Path(requested_bootstrap_grant)
        bootstrap_grant = validate_bootstrap_recovery_grant(
            bootstrap_grant_path,
            instance_id=args.instance_id,
            instance_dir=instance_dir,
            root_thread_id=args.root_thread_id,
            state_dir=state_dir,
            version=server_version,
            pin=pin,
        )
    electron_data_dir = ensure_private_dir(instance_dir / "electron-data")
    desktop_isolation_argument = f"{USER_DATA_SWITCH}{electron_data_dir}"
    project: Path | None = None
    if args.project is not None:
        project = Path(args.project)
        if not project.is_absolute() or project.is_symlink() or not project.is_dir():
            raise AdapterError("project-path-invalid")
        project = project.resolve(strict=True)
    command = desktop_launch_command(desktop, electron_data_dir, project)
    session_path = instance_dir / "session.json"
    with session_lock(instance_dir):
        if session_path.exists():
            existing = read_private_json(session_path)
            if existing.get("armed") is True and process_command(existing.get("desktop_pid")):
                raise AdapterError("host-already-running")
        now = utc_now()
        token = secrets.token_urlsafe(32)
        socket_path = short_socket_path(args.instance_id, token)
        session = {
            "adapter_sha256": digest(ADAPTER_PATH),
            "approval_grant_enabled": grant_enabled,
            "approval_grant_sha256": approval_grant_digest(),
            "app_server_pid": None,
            "armed": True,
            "bootstrap_recovery_grant_id": (
                bootstrap_grant["grant_id"] if bootstrap_grant is not None else None
            ),
            "bootstrap_recovery_grant_path": (
                str(bootstrap_grant_path) if bootstrap_grant_path is not None else None
            ),
            "bootstrap_recovery_grant_sha256": (
                digest(bootstrap_grant_path) if bootstrap_grant_path is not None else None
            ),
            "codex_cli": str(codex_cli),
            "codex_cli_sha256": digest(codex_cli),
            "created_at": iso(now),
            "desktop_executable": str(desktop),
            "desktop_executable_sha256": digest(desktop),
            "desktop_isolation_argument": desktop_isolation_argument,
            "desktop_pid": None,
            "dispatcher_adoption_sha256": adoption_sha256,
            "electron_data_dir": str(electron_data_dir),
            "expires_at": iso(now + dt.timedelta(seconds=SESSION_TTL_SECONDS)),
            "hook_bundle_sha256": hook_bundle_digest(),
            "instance_id": args.instance_id,
            "plugin_version": server_version,
            "proof_sha256": digest(instance_dir / "live-proof.json"),
            "proxy_pid": None,
            "root_thread_id": args.root_thread_id,
            "session_version": SESSION_VERSION,
            "socket_path": str(socket_path),
            "state_dir": str(state_dir),
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        }
        atomic_private_json(session_path, session)
    log_path = instance_dir / "desktop.log"
    descriptor = -1
    try:
        descriptor = os.open(
            log_path,
            os.O_CREAT
            | os.O_WRONLY
            | os.O_APPEND
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        log_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(log_metadata.st_mode)
            or log_metadata.st_uid != os.getuid()
            or (log_metadata.st_mode & 0o777) != 0o600
        ):
            raise AdapterError("desktop-log-invalid")
    except (AdapterError, OSError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        disarm_session(instance_dir, session_path)
        if isinstance(exc, AdapterError):
            raise
        raise AdapterError("desktop-log-invalid") from exc
    environment = dict(os.environ)
    for name in ADAPTER_ENV_VARS:
        environment.pop(name, None)
    environment.pop("ROOT_ORCHESTRATOR_ROLE", None)
    environment["CODEX_APP_SERVER_FORCE_CLI"] = "1"
    environment["CODEX_CLI_PATH"] = str(ADAPTER_PATH)
    environment["CODEX_ELECTRON_USER_DATA_PATH"] = str(electron_data_dir)
    environment[SESSION_ENV] = str(session_path)
    environment[TOKEN_ENV] = token
    environment[REAL_CODEX_ENV] = str(codex_cli)
    try:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=descriptor,
                stderr=descriptor,
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            disarm_session(instance_dir, session_path)
            raise AdapterError("desktop-host-start-failed") from exc
    finally:
        os.close(descriptor)
    time.sleep(1)
    if process.poll() is not None:
        disarm_session(instance_dir, session_path)
        raise AdapterError("desktop-host-exited-during-startup")
    with session_lock(instance_dir):
        current = read_private_json(session_path)
        current["desktop_pid"] = process.pid
        atomic_private_json(session_path, current)
    try:
        proxy_observed = wait_for_proxy(session_path)
    except AdapterError:
        proxy_observed = False
    if not proxy_observed:
        disarm_session(instance_dir, session_path)
        if process.poll() is None:
            process.terminate()
        raise AdapterError("desktop-host-proxy-not-observed")
    return {
        "ok": True,
        "result": {
            "desktop_pid": process.pid,
            "global_configuration_changed": False,
            "instance_id": args.instance_id,
            "normal_desktop_recovery_available": True,
            "root_thread_id": args.root_thread_id,
            "bootstrap_recovery_grant_id": (
                bootstrap_grant["grant_id"] if bootstrap_grant is not None else None
            ),
            "bootstrap_recovery_grant_bound": bootstrap_grant is not None,
            "prompt_free_control_grant_verified": grant_enabled,
            "runtime_pin_verified": True,
            "status": "STARTING",
            "valid_until": current["expires_at"],
        },
    }


def session_status(instance_dir: Path) -> dict[str, Any]:
    session_path = ensure_private_dir(instance_dir) / "session.json"
    if not session_path.exists():
        return {"ok": True, "result": {"status": "NOT_CONFIGURED"}}
    session = read_private_json(session_path)
    desktop_alive = desktop_process_matches(session)
    proxy_alive = process_matches(
        session.get("proxy_pid"), str(ADAPTER_PATH), "app-server"
    )
    expired = parse_utc(session.get("expires_at")) < utc_now()
    return {
        "ok": True,
        "result": {
            "armed": session.get("armed") is True and not expired,
            "desktop_alive": desktop_alive,
            "global_configuration_changed": False,
            "instance_id": session.get("instance_id"),
            "normal_desktop_recovery_available": True,
            "prompt_free_control_grant_verified": session.get(
                "approval_grant_enabled"
            )
            is True,
            "proxy_alive": proxy_alive,
            "root_thread_id": session.get("root_thread_id"),
            "status": (
                "RUNNING"
                if session.get("armed") is True and desktop_alive and proxy_alive and not expired
                else "DISARMED" if session.get("armed") is not True or expired
                else "STARTING"
            ),
        },
    }


def stop(instance_dir: Path, timeout: float) -> dict[str, Any]:
    directory = ensure_private_dir(instance_dir)
    session_path = directory / "session.json"
    if not session_path.exists():
        return {"ok": True, "result": {"status": "NOT_CONFIGURED"}}
    with session_lock(directory):
        session = read_private_json(session_path)
        session["armed"] = False
        atomic_private_json(session_path, session)
    targets = [
        (
            session.get("desktop_pid"),
            (session.get("desktop_executable"), session.get("desktop_isolation_argument")),
        ),
        (session.get("proxy_pid"), (str(ADAPTER_PATH), "app-server")),
        (session.get("app_server_pid"), (session.get("codex_cli"), "app-server")),
    ]
    signaled: list[int] = []
    for pid, expected in targets:
        if isinstance(pid, int) and process_matches(pid, *expected):
            try:
                os.kill(pid, signal.SIGTERM)
                signaled.append(pid)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + max(0.0, min(timeout, 10.0))
    while time.monotonic() < deadline:
        if all(process_command(pid) is None for pid in signaled):
            break
        time.sleep(0.1)
    survivors = [pid for pid in signaled if process_command(pid) is not None]
    return {
        "ok": not survivors,
        "result": {
            "forced_kill_used": False,
            "global_configuration_changed": False,
            "signaled_pids": signaled,
            "status": "STOPPED" if not survivors else "STOPPING",
            "surviving_pids": survivors,
        },
    }


def app_server_argv(arguments: list[str]) -> bool:
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value == "app-server":
            break
        if value in {"-c", "--config", "--enable", "--disable"}:
            index += 2
            continue
        if value.startswith(("--config=", "--enable=", "--disable=")):
            index += 1
            continue
        return False
    if index >= len(arguments) or arguments[index] != "app-server":
        return False
    disallowed = {"daemon", "proxy", "generate-ts", "generate-json-schema"}
    return not any(value in disallowed for value in arguments[index + 1 :])


def validate_session_from_environment() -> tuple[Path, dict[str, Any]]:
    session_raw = os.environ.get(SESSION_ENV, "").strip()
    token = os.environ.get(TOKEN_ENV, "")
    real_codex = os.environ.get(REAL_CODEX_ENV, "").strip()
    if not session_raw or not token or not real_codex:
        raise AdapterError("host-session-environment-missing")
    session_path = Path(session_raw)
    session = read_private_json(session_path)
    exact_keys(
        session,
        {
            "adapter_sha256",
            "approval_grant_enabled",
            "approval_grant_sha256",
            "app_server_pid",
            "armed",
            "bootstrap_recovery_grant_id",
            "bootstrap_recovery_grant_path",
            "bootstrap_recovery_grant_sha256",
            "codex_cli",
            "codex_cli_sha256",
            "created_at",
            "desktop_executable",
            "desktop_executable_sha256",
            "desktop_isolation_argument",
            "desktop_pid",
            "dispatcher_adoption_sha256",
            "electron_data_dir",
            "expires_at",
            "hook_bundle_sha256",
            "instance_id",
            "plugin_version",
            "proof_sha256",
            "proxy_pid",
            "root_thread_id",
            "session_version",
            "socket_path",
            "state_dir",
            "token_sha256",
        },
        {
            "adapter_sha256",
            "approval_grant_enabled",
            "approval_grant_sha256",
            "armed",
            "bootstrap_recovery_grant_id",
            "bootstrap_recovery_grant_path",
            "bootstrap_recovery_grant_sha256",
            "codex_cli",
            "codex_cli_sha256",
            "desktop_executable",
            "desktop_executable_sha256",
            "desktop_isolation_argument",
            "dispatcher_adoption_sha256",
            "electron_data_dir",
            "expires_at",
            "hook_bundle_sha256",
            "instance_id",
            "plugin_version",
            "proof_sha256",
            "root_thread_id",
            "session_version",
            "socket_path",
            "state_dir",
            "token_sha256",
        },
    )
    token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()
    codex_path = secure_file(Path(real_codex), executable=True)
    electron_data_dir = existing_private_dir(session_path.parent / "electron-data")
    try:
        state_dir = existing_private_dir(Path(str(session.get("state_dir"))))
        proof_path = session_path.parent / "live-proof.json"
        proof = read_private_json(proof_path)
        proof_sha256 = digest(proof_path)
    except (AdapterError, OSError):
        raise AdapterError("host-session-invalid") from None
    bootstrap_path_raw = session.get("bootstrap_recovery_grant_path")
    bootstrap_id = session.get("bootstrap_recovery_grant_id")
    bootstrap_sha256 = session.get("bootstrap_recovery_grant_sha256")
    bootstrap_valid = False
    if bootstrap_path_raw is None and bootstrap_id is None and bootstrap_sha256 is None:
        bootstrap_valid = True
    elif (
        isinstance(bootstrap_path_raw, str)
        and isinstance(bootstrap_id, str)
        and isinstance(bootstrap_sha256, str)
        and SHA256.fullmatch(bootstrap_sha256) is not None
    ):
        try:
            bootstrap_path = Path(bootstrap_path_raw)
            bootstrap_value = read_private_json(bootstrap_path)
            bootstrap_valid = bool(
                bootstrap_path.parent == session_path.parent
                and digest(bootstrap_path) == bootstrap_sha256
                and bootstrap_value.get("grant_id") == bootstrap_id
                and bootstrap_value.get("instance_id") == session.get("instance_id")
                and bootstrap_value.get("root_thread_id")
                == session.get("root_thread_id")
                and bootstrap_value.get("state_dir") == session.get("state_dir")
                and bootstrap_value.get("plugin_version")
                == session.get("plugin_version")
            )
        except (AdapterError, OSError):
            bootstrap_valid = False
    if (
        session.get("session_version") != SESSION_VERSION
        or not isinstance(session.get("approval_grant_enabled"), bool)
        or session.get("armed") is not True
        or parse_utc(session.get("expires_at")) < utc_now()
        or session.get("codex_cli") != str(codex_path)
        or session.get("codex_cli_sha256") != digest(codex_path)
        or session.get("state_dir") != str(state_dir)
        or session.get("plugin_version") != manifest().get("version")
        or session.get("electron_data_dir") != str(electron_data_dir)
        or session.get("desktop_isolation_argument")
        != f"{USER_DATA_SWITCH}{electron_data_dir}"
        or session.get("adapter_sha256") != digest(ADAPTER_PATH)
        or session.get("approval_grant_sha256") != approval_grant_digest()
        or (
            session.get("approval_grant_enabled") is True
            and (
                not isinstance(session.get("dispatcher_adoption_sha256"), str)
                or SHA256.fullmatch(str(session.get("dispatcher_adoption_sha256")))
                is None
            )
        )
        or (
            session.get("approval_grant_enabled") is False
            and session.get("dispatcher_adoption_sha256") is not None
        )
        or proof.get("prompt_free_control_grant_verified")
        is not session.get("approval_grant_enabled")
        or proof.get("dispatcher_adoption_sha256")
        != session.get("dispatcher_adoption_sha256")
        or proof.get("plugin_version") != session.get("plugin_version")
        or session.get("hook_bundle_sha256") != hook_bundle_digest()
        or session.get("proof_sha256") != proof_sha256
        or not bootstrap_valid
        or not hmac.compare_digest(str(session.get("token_sha256")), token_sha256)
    ):
        raise AdapterError("host-session-invalid")
    return session_path, session


class AttestationServer:
    def __init__(self, session_path: Path, session: dict[str, Any]) -> None:
        self.session_path = session_path
        self.instance_id = str(session["instance_id"])
        self.root_thread_id = str(session["root_thread_id"])
        self.approval_grant_enabled = session.get("approval_grant_enabled") is True
        self.path = Path(str(session["socket_path"]))
        self.listener: socket.socket | None = None
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        ensure_private_dir(self.path.parent)
        if self.path.exists() or self.path.is_symlink():
            try:
                metadata = self.path.lstat()
            except OSError as exc:
                raise AdapterError("attestation-socket-invalid") from exc
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise AdapterError("attestation-socket-invalid")
            self.path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.path))
        os.chmod(self.path, 0o600)
        listener.listen(32)
        listener.settimeout(0.2)
        self.listener = listener
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        assert self.listener is not None
        while not self.stopping.is_set():
            try:
                connection, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(0.2)
                try:
                    raw = bytearray()
                    while len(raw) <= MAX_ATTESTATION_BYTES:
                        chunk = connection.recv(1024)
                        if not chunk:
                            break
                        raw.extend(chunk)
                        if b"\n" in chunk:
                            break
                    if b"\n" not in raw:
                        continue
                    request = strict_json(
                        bytes(raw).split(b"\n", 1)[0].decode("utf-8"),
                        maximum=MAX_ATTESTATION_BYTES,
                    )
                    if not isinstance(request, dict):
                        continue
                    exact_keys(
                        request,
                        {"hook_event_name", "interface_version", "nonce", "session_id"},
                        {"hook_event_name", "interface_version", "nonce", "session_id"},
                    )
                    current = read_private_json(self.session_path)
                    session_id = request.get("session_id")
                    nonce = request.get("nonce")
                    if (
                        current.get("armed") is not True
                        or parse_utc(current.get("expires_at")) < utc_now()
                        or current.get("adapter_sha256") != digest(ADAPTER_PATH)
                        or current.get("hook_bundle_sha256") != hook_bundle_digest()
                        or current.get("instance_id") != self.instance_id
                        or current.get("root_thread_id") != self.root_thread_id
                        or current.get("approval_grant_enabled")
                        is not self.approval_grant_enabled
                        or current.get("socket_path") != str(self.path)
                        or request.get("interface_version") != INTERFACE_VERSION
                        or request.get("hook_event_name") not in {"PreToolUse", "PostToolUse"}
                        or not isinstance(session_id, str)
                        or OPAQUE.fullmatch(session_id) is None
                        or not isinstance(nonce, str)
                        or NONCE.fullmatch(nonce) is None
                    ):
                        continue
                    response = {
                        "control_grant": (
                            "PROMPT_FREE"
                            if self.approval_grant_enabled
                            else "PROMPTED"
                        ),
                        "decision": "ROOT" if session_id == self.root_thread_id else "WORKER",
                        "instance_id": self.instance_id,
                        "interface_version": INTERFACE_VERSION,
                        "nonce": nonce,
                        "session_id": session_id,
                    }
                    connection.sendall(
                        json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
                        + b"\n"
                    )
                except (AdapterError, OSError, TimeoutError, UnicodeDecodeError):
                    continue

    def stop(self) -> None:
        self.stopping.set()
        if self.listener is not None:
            self.listener.close()
        if self.thread is not None:
            self.thread.join(timeout=1)
        try:
            if self.path.is_socket() and not self.path.is_symlink():
                self.path.unlink()
        except OSError:
            pass


def copy_stream(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    close: bool,
    stopping: threading.Event | None = None,
) -> None:
    """Forward a pipe without leaving a buffered-reader daemon at shutdown."""

    try:
        try:
            descriptor: int | None = source.fileno()
        except (AttributeError, OSError, ValueError):
            descriptor = None
        while True:
            if stopping is not None and stopping.is_set():
                break
            if descriptor is not None:
                try:
                    readable, _, _ = select.select([descriptor], [], [], 0.1)
                except (OSError, ValueError):
                    break
                if not readable:
                    continue
                chunk = os.read(descriptor, 64 * 1024)
            else:
                chunk = source.read(64 * 1024)
            if not chunk:
                break
            destination.write(chunk)
            destination.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        if close:
            try:
                destination.close()
            except (OSError, ValueError):
                pass


def run_proxy(arguments: list[str]) -> int:
    if not app_server_argv(arguments):
        raise AdapterError("only-foreground-app-server-is-allowed")
    session_path, session = validate_session_from_environment()
    server = AttestationServer(session_path, session)
    server.start()
    child: subprocess.Popen[bytes] | None = None
    input_thread: threading.Thread | None = None
    output_thread: threading.Thread | None = None
    input_stopping = threading.Event()
    output_stopping = threading.Event()
    try:
        child_environment = dict(os.environ)
        for name in ADAPTER_ENV_VARS:
            child_environment.pop(name, None)
        child_environment.pop("ROOT_ORCHESTRATOR_ROLE", None)
        child_environment[SOCKET_ENV] = str(server.path)
        child_environment[INSTANCE_ENV] = str(session["instance_id"])
        if session.get("bootstrap_recovery_grant_path") is not None:
            child_environment[BOOTSTRAP_GRANT_ENV] = str(
                session["bootstrap_recovery_grant_path"]
            )
        real_codex = Path(str(session["codex_cli"]))
        child_arguments = isolated_app_server_arguments(
            arguments,
            grant_enabled=session.get("approval_grant_enabled") is True,
        )
        try:
            child = subprocess.Popen(
                [str(real_codex), *child_arguments],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                env=child_environment,
                close_fds=True,
            )
        except OSError as exc:
            raise AdapterError("real-app-server-start-failed") from exc
        with session_lock(session_path.parent):
            current = read_private_json(session_path)
            if current.get("armed") is not True:
                child.terminate()
                return 1
            current["proxy_pid"] = os.getpid()
            current["app_server_pid"] = child.pid
            atomic_private_json(session_path, current)
        assert child.stdin is not None and child.stdout is not None
        input_thread = threading.Thread(
            target=copy_stream,
            args=(sys.stdin.buffer, child.stdin),
            kwargs={"close": True, "stopping": input_stopping},
        )
        output_thread = threading.Thread(
            target=copy_stream,
            args=(child.stdout, sys.stdout.buffer),
            kwargs={"close": False, "stopping": output_stopping},
        )
        input_thread.start()
        output_thread.start()

        def terminate_child(_signum: int, _frame: Any) -> None:
            if child is not None and child.poll() is None:
                child.terminate()

        signal.signal(signal.SIGTERM, terminate_child)
        signal.signal(signal.SIGINT, terminate_child)
        return_code = child.wait()
        input_stopping.set()
        input_thread.join(timeout=2)
        output_thread.join(timeout=2)
        if output_thread.is_alive():
            output_stopping.set()
            output_thread.join(timeout=2)
        if input_thread.is_alive() or output_thread.is_alive():
            raise AdapterError("proxy-stream-shutdown-failed")
        return return_code
    finally:
        input_stopping.set()
        output_stopping.set()
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        for thread in (input_thread, output_thread):
            if thread is not None:
                thread.join(timeout=2)
        server.stop()
        with session_lock(session_path.parent):
            current = read_private_json(session_path)
            if current.get("proxy_pid") == os.getpid():
                current["proxy_pid"] = None
                current["app_server_pid"] = None
                atomic_private_json(session_path, current)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="operation", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--instance-dir", required=True)
    verify_parser.add_argument("--state-dir", required=True)
    verify_parser.add_argument("--codex-cli", required=True)
    verify_parser.add_argument("--timeout", type=int, default=120, choices=range(30, 301))
    launch_parser = sub.add_parser("launch")
    launch_parser.add_argument("--instance-id", required=True)
    launch_parser.add_argument("--instance-dir", required=True)
    launch_parser.add_argument("--root-thread-id", required=True)
    launch_parser.add_argument("--state-dir", required=True)
    launch_parser.add_argument("--codex-cli", required=True)
    launch_parser.add_argument("--desktop-executable", required=True)
    launch_parser.add_argument("--project")
    launch_parser.add_argument("--bootstrap-grant")
    grant_parser = sub.add_parser("issue-bootstrap-recovery-grant")
    grant_parser.add_argument("--instance-id", required=True)
    grant_parser.add_argument("--instance-dir", required=True)
    grant_parser.add_argument("--root-thread-id", required=True)
    grant_parser.add_argument("--state-dir", required=True)
    grant_parser.add_argument("--codex-cli", required=True)
    grant_parser.add_argument("--project-root", required=True)
    grant_parser.add_argument("--base-sha", required=True)
    grant_parser.add_argument("--grant-id", required=True)
    grant_parser.add_argument("--request-id", required=True)
    grant_parser.add_argument("--authorization-request-id", required=True)
    grant_parser.add_argument("--decision-request-id", required=True)
    grant_parser.add_argument("--decision-id", required=True)
    grant_parser.add_argument("--ticket-id", required=True)
    grant_parser.add_argument("--task-id", required=True)
    grant_parser.add_argument("--external-thread-id", required=True)
    grant_parser.add_argument("--expected-state-revision", type=int, required=True)
    grant_parser.add_argument("--expected-policy-revision", type=int, required=True)
    grant_parser.add_argument(
        "--expected-configured-capacity", type=int, required=True
    )
    grant_parser.add_argument("--policy-snapshot-revision", type=int, required=True)
    grant_parser.add_argument("--lease-epoch", type=int, required=True)
    grant_parser.add_argument("--fencing-token", type=int, required=True)
    grant_parser.add_argument(
        "--lifetime-seconds",
        type=int,
        default=BOOTSTRAP_GRANT_MAX_TTL_SECONDS,
    )
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--instance-dir", required=True)
    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("--instance-dir", required=True)
    stop_parser.add_argument("--timeout", type=float, default=5.0)
    return result


def emit(value: Mapping[str, Any], *, stream: Any = sys.stdout) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), file=stream)


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and arguments[0] not in {
        "verify",
        "issue-bootstrap-recovery-grant",
        "launch",
        "status",
        "stop",
    }:
        try:
            return run_proxy(arguments)
        except AdapterError as exc:
            print(f"desktop-host-adapter: {exc}", file=sys.stderr)
            return 2
    try:
        args = parser().parse_args(arguments)
        if args.operation == "verify":
            value = verify(args)
        elif args.operation == "issue-bootstrap-recovery-grant":
            value = issue_bootstrap_recovery_grant(args)
        elif args.operation == "launch":
            value = launch(args)
        elif args.operation == "status":
            value = session_status(Path(args.instance_dir))
        else:
            value = stop(Path(args.instance_dir), args.timeout)
        emit(value)
        return 0 if value.get("ok") is True else 2
    except AdapterError as exc:
        emit({"ok": False, "error": {"code": str(exc)}}, stream=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError):
        emit(
            {"ok": False, "error": {"code": "desktop-host-operation-failed"}},
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
