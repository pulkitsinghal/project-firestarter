"""Typed lifecycle-envelope and single-use execution-permit verification.

This module is a control-plane boundary only.  It validates deterministic
plans/results and may authorize an exact plan for a *separate* executor
handoff.  It has no executor, shell, subprocess, network client, socket,
launchd, Docker, or Ollama integration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import sqlite3
import stat
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

SCHEMA_VERSION = 1
SUPERVISOR_CONTRACT_VERSION = "0.1.0"
PERMIT_POLICY_VERSION = "pm-execution-permit/1"
HANDOFF_RECEIPT_VERSION = "execution-handoff-receipt/1"
MAX_ENVELOPE_BYTES = 256 * 1024
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_STEPS = 512

SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")
KEEP_ALIVE_RE = re.compile(r"^(?:-1|[1-9][0-9]{0,5}(?:ms|s|m|h))$")
SAFE_HTTP_PATH_RE = re.compile(r"^/[A-Za-z0-9._~/-]{0,255}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
KEY_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
TELEMETRY_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
ERROR_MESSAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.,:;()'-]{0,95}$")
DOMAIN_TARGET_RE = re.compile(r"^gui/[1-9][0-9]{0,9}$")

PLAN_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "supervisor_contract_version",
        "target_service_id",
        "intent",
        "dry_run",
        "steps",
        "plan_digest",
    }
)
RESULT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "plan_digest",
        "status",
        "completed_steps",
        "failed_step",
        "readiness_proved",
        "rollback_status",
        "error",
    }
)
PERMIT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "policy_version",
        "permit_id",
        "authorization_phase",
        "issued_at",
        "expires_at",
        "nonce",
        "key_id",
        "plan_digest",
        "target_service_id",
        "intent",
        "actions",
        "adapter_set",
        "producer_schema_digest",
        "catalog_digest",
        "executor_generation",
        "state_generation",
        "signature",
    }
)
CONTRACT_PIN_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "source_repository",
        "source_ref",
        "plan_schema_path",
        "plan_schema_sha256",
        "catalog_fixture_path",
        "catalog_fixture_sha256",
        "observations_fixture_path",
        "observations_fixture_sha256",
        "plan_fixture_path",
        "plan_fixture_sha256",
        "result_fixture_path",
        "result_fixture_sha256",
        "untrusted_permit_fixture_path",
        "untrusted_permit_fixture_sha256",
        "canonical_plan_digest",
    }
)
PINNED_LOCAL_AI_CONTRACT: dict[str, object] = {
    "schema_version": 1,
    "status": "pinned",
    "source_repository": "local-ai",
    "source_ref": "3986befb06106b66795444d54f8513ead83f76b0",
    "plan_schema_path": "docs/service-lifecycle-1.0.schema.json",
    "plan_schema_sha256": (
        "a424f6a5b73641bdc6bdafc3411d49f7"
        "a239c663cbb0dd62eea665cfb6d76d97"
    ),
    "catalog_fixture_path": (
        "tests/fixtures/service-lifecycle-catalog-1.synthetic.json"
    ),
    "catalog_fixture_sha256": (
        "6d0b7a440c2f6758b0b01482a5a508d"
        "ba12b8c191938949854ad1189718fa5f1"
    ),
    "observations_fixture_path": (
        "tests/fixtures/service-lifecycle-observations-1.synthetic.json"
    ),
    "observations_fixture_sha256": (
        "1ecbdbb75571f353469120bfd53c4be7"
        "a82ae03802d0bde33013a0c1bcf6edda"
    ),
    "plan_fixture_path": (
        "tests/fixtures/service-lifecycle-plan-1.synthetic.json"
    ),
    "plan_fixture_sha256": (
        "deca956500d797e1d956692b120f082b4"
        "f6f417cd6f0a65c00bef342545962b7"
    ),
    "result_fixture_path": (
        "tests/fixtures/service-lifecycle-result-1.synthetic.json"
    ),
    "result_fixture_sha256": (
        "ee8a33252684ab9adb420b61f9ab4b3c"
        "d2f0c9d4b992df7e94f682d49c6abecb"
    ),
    "untrusted_permit_fixture_path": (
        "tests/fixtures/service-lifecycle-permit-1.untrusted.synthetic.json"
    ),
    "untrusted_permit_fixture_sha256": (
        "82d77161f1dfa3fbb448d80f5dd3baa8"
        "cba755e54bc516a82fa0c744734fa526"
    ),
    "canonical_plan_digest": (
        "9099a1ad8f5d19a261243a29e13f0719"
        "f9663af3d7a28201adef99e76d7d3796"
    ),
}
HANDOFF_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "receipt_version",
        "decision",
        "policy_version",
        "receipt_id",
        "receipt_nonce",
        "issued_at",
        "expires_at",
        "verifier_instance_id",
        "receipt_key_id",
        "target_service_id",
        "intent",
        "authorization_phase",
        "plan_digest",
        "actions",
        "adapter_set",
        "permit_id",
        "permit_fingerprint",
        "producer_schema_digest",
        "catalog_digest",
        "executor_generation",
        "state_generation",
        "verifier_artifact_digest",
        "contract_pin_digest",
        "rollback_authorized",
        "signature",
    }
)
PLAN_STEP_KEYS = frozenset(
    {
        "sequence",
        "service_id",
        "adapter",
        "operation",
        "resource_key",
        "argv",
        "http_request",
        "readiness",
        "rollback",
    }
)
INTENT_OPERATIONS = {
    "ensure-ready": frozenset(
        {"bootstrap", "start", "load", "check-readiness"}
    ),
    "complete-stop": frozenset(
        {"bootout", "stop", "unload", "check-readiness"}
    ),
    "restart": frozenset(
        {
            "bootstrap",
            "bootout",
            "kickstart",
            "start",
            "stop",
            "load",
            "unload",
            "check-readiness",
        }
    ),
}
ADAPTER_OPERATIONS = {
    "launchd": frozenset(
        {"bootstrap", "bootout", "kickstart", "check-readiness"}
    ),
    "docker-compose": frozenset({"start", "stop", "check-readiness"}),
    "ollama": frozenset({"load", "unload", "check-readiness"}),
}
INVERSE_OPERATIONS = {
    "bootstrap": "bootout",
    "bootout": "bootstrap",
    "start": "stop",
    "stop": "start",
    "load": "unload",
    "unload": "load",
}
RESULT_OUTCOMES = frozenset(
    {"dry-run", "succeeded", "failed", "rolled-back"}
)
ROLLBACK_STATUSES = frozenset({"not-run", "not-needed", "succeeded", "failed"})
RESULT_ERROR_MESSAGES = {
    "synthetic-failure": "synthetic lifecycle proof failed",
    "readiness-timeout": "synthetic readiness proof timed out",
    "rollback-failed": "synthetic rollback failed",
    "rollback-incomplete": "synthetic rollback was incomplete",
}


class EnvelopeError(ValueError):
    """An input envelope is malformed, inconsistent, or outside policy."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PermitRefusal(RuntimeError):
    """A permit cannot authorize the requested exact plan."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PermitStateError(RuntimeError):
    """The durable nonce store is unsafe, corrupt, or unavailable."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_json_bytes(value: object) -> bytes:
    """Return the contract's deterministic UTF-8 JSON representation."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise EnvelopeError("NON_CANONICAL_JSON") from exc
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise EnvelopeError("ENVELOPE_TOO_LARGE")
    return encoded


def load_contract_pin(path: str | Path) -> dict[str, object]:
    """Load an exact merged local-ai contract pin or refuse provisional data."""

    pin_path = Path(path)
    try:
        info = pin_path.lstat()
    except OSError as exc:
        raise EnvelopeError("CONTRACT_PIN_UNREADABLE") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_size > MAX_ENVELOPE_BYTES
    ):
        raise EnvelopeError("UNSAFE_CONTRACT_PIN")
    try:
        raw = json.loads(pin_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvelopeError("INVALID_CONTRACT_PIN_JSON") from exc
    pin = _exact_object(raw, CONTRACT_PIN_KEYS, "INVALID_CONTRACT_PIN_KEYS")
    if (
        pin.get("schema_version") != SCHEMA_VERSION
        or pin.get("source_repository") != "local-ai"
    ):
        raise EnvelopeError("INVALID_CONTRACT_PIN")
    if pin.get("status") != "pinned":
        raise EnvelopeError("UNPINNED_PRODUCER_CONTRACT")
    _strict_string(
        pin.get("source_ref"), re.compile(r"^[0-9a-f]{40}$"), "INVALID_SOURCE_REF"
    )
    expected_paths = {
        "plan_schema_path": "docs/service-lifecycle-1.0.schema.json",
        "catalog_fixture_path": (
            "tests/fixtures/service-lifecycle-catalog-1.synthetic.json"
        ),
        "observations_fixture_path": (
            "tests/fixtures/service-lifecycle-observations-1.synthetic.json"
        ),
        "plan_fixture_path": (
            "tests/fixtures/service-lifecycle-plan-1.synthetic.json"
        ),
        "result_fixture_path": (
            "tests/fixtures/service-lifecycle-result-1.synthetic.json"
        ),
        "untrusted_permit_fixture_path": (
            "tests/fixtures/"
            "service-lifecycle-permit-1.untrusted.synthetic.json"
        ),
    }
    for key, expected in expected_paths.items():
        if pin.get(key) != expected:
            raise EnvelopeError("INVALID_CONTRACT_ARTIFACT_PATH")
    for key in (
        "plan_schema_sha256",
        "catalog_fixture_sha256",
        "observations_fixture_sha256",
        "plan_fixture_sha256",
        "result_fixture_sha256",
        "untrusted_permit_fixture_sha256",
        "canonical_plan_digest",
    ):
        _strict_string(pin.get(key), SHA256_RE, "INVALID_CONTRACT_ARTIFACT_DIGEST")
    if pin != PINNED_LOCAL_AI_CONTRACT:
        raise EnvelopeError("CONTRACT_PIN_MISMATCH")
    return dict(pin)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exact_object(
    raw: object, keys: frozenset[str], code: str
) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != keys:
        raise EnvelopeError(code)
    if any(not isinstance(key, str) for key in raw):
        raise EnvelopeError(code)
    return raw


def _strict_int(value: object, code: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EnvelopeError(code)
    if not minimum <= value <= maximum:
        raise EnvelopeError(code)
    return value


def _strict_string(
    value: object, pattern: re.Pattern[str], code: str
) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise EnvelopeError(code)
    return value


def _safe_absolute_path(
    value: object, suffixes: tuple[str, ...], code: str
) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or len(value) > 1024
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise EnvelopeError(code)
    path = value
    pure = PurePosixPath(path)
    if (
        not pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or not pure.name
        or not path.endswith(suffixes)
    ):
        raise EnvelopeError(code)
    return path


def _safe_compose_path(value: object) -> str:
    return _safe_absolute_path(value, (".yaml", ".yml"), "UNSAFE_COMPOSE_PATH")


def _loopback_http_url(
    value: object, code: str, *, required_path: str | None = None
) -> str:
    if not isinstance(value, str):
        raise EnvelopeError(code)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise EnvelopeError(code) from exc
    if (
        parsed.scheme != "http"
        or host is None
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise EnvelopeError(code)
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise EnvelopeError(code) from exc
    if not address.is_loopback:
        raise EnvelopeError(code)
    decoded_path = unquote(parsed.path)
    if (
        not SAFE_HTTP_PATH_RE.fullmatch(parsed.path)
        or "\x00" in decoded_path
        or "\\" in decoded_path
        or any(part in {".", ".."} for part in decoded_path.split("/"))
    ):
        raise EnvelopeError(code)
    if required_path is not None and parsed.path != required_path:
        raise EnvelopeError(code)
    canonical_host = f"[{address.compressed}]" if address.version == 6 else str(address)
    return f"http://{canonical_host}:{port}{parsed.path}"


def _launchd_resource(operation: str, argv: object) -> str:
    if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
        raise EnvelopeError("INVALID_LAUNCHD_ARGV")
    domain: str
    label: str
    if operation == "bootstrap":
        if (
            len(argv) != 4
            or argv[:2] != ["/bin/launchctl", "bootstrap"]
        ):
            raise EnvelopeError("INVALID_LAUNCHD_ARGV")
        domain = _strict_string(argv[2], DOMAIN_TARGET_RE, "INVALID_LAUNCHD_TARGET")
        plist_path = _safe_absolute_path(
            argv[3], (".plist",), "UNSAFE_PLIST_PATH"
        )
        pure_path = PurePosixPath(plist_path)
        label = pure_path.stem
        _strict_string(label, SAFE_LABEL_RE, "INVALID_LAUNCHD_LABEL")
    elif operation in {"bootout", "kickstart"}:
        prefix = (
            ["/bin/launchctl", "bootout"]
            if operation == "bootout"
            else ["/bin/launchctl", "kickstart", "-k"]
        )
        if len(argv) != len(prefix) + 1 or argv[: len(prefix)] != prefix:
            raise EnvelopeError("INVALID_LAUNCHD_ARGV")
        target = argv[-1]
        if "/" not in target:
            raise EnvelopeError("INVALID_LAUNCHD_TARGET")
        domain, label = target.rsplit("/", 1)
        _strict_string(domain, DOMAIN_TARGET_RE, "INVALID_LAUNCHD_TARGET")
        _strict_string(label, SAFE_LABEL_RE, "INVALID_LAUNCHD_LABEL")
    else:
        raise EnvelopeError("INVALID_LAUNCHD_OPERATION")
    return f"launchd:{domain}:{label}"


def _compose_resource(operation: str, argv: object) -> str:
    if (
        not isinstance(argv, list)
        or any(not isinstance(item, str) for item in argv)
        or len(argv) != 8
        or argv[0] not in {"/usr/local/bin/docker", "/opt/homebrew/bin/docker"}
        or argv[1:3] != ["compose", "--project-name"]
        or argv[4] != "--file"
        or argv[6] != operation
    ):
        raise EnvelopeError("INVALID_COMPOSE_ARGV")
    project = _strict_string(argv[3], SERVICE_ID_RE, "INVALID_COMPOSE_PROJECT")
    _safe_compose_path(argv[5])
    service = _strict_string(argv[7], SERVICE_ID_RE, "INVALID_COMPOSE_SERVICE")
    return f"compose:{project}:{service}"


def _ollama_resource(operation: str, http_request: object) -> str:
    request = _exact_object(
        http_request,
        frozenset({"method", "url", "json"}),
        "INVALID_OLLAMA_REQUEST",
    )
    if request.get("method") != "POST":
        raise EnvelopeError("INVALID_OLLAMA_REQUEST")
    _loopback_http_url(
        request.get("url"),
        "UNSAFE_OLLAMA_URL",
        required_path="/api/generate",
    )
    expected_json_keys = (
        frozenset({"model", "keep_alive", "stream"})
        if operation == "load"
        else frozenset({"model", "keep_alive"})
    )
    body = _exact_object(
        request.get("json"), expected_json_keys, "INVALID_OLLAMA_JSON"
    )
    model = _strict_string(body.get("model"), MODEL_RE, "INVALID_OLLAMA_MODEL")
    if operation == "load":
        _strict_string(
            body.get("keep_alive"), KEEP_ALIVE_RE, "INVALID_KEEP_ALIVE"
        )
        if body.get("stream") is not False:
            raise EnvelopeError("INVALID_OLLAMA_LOAD")
    elif operation == "unload":
        if body.get("keep_alive") != 0:
            raise EnvelopeError("INVALID_OLLAMA_UNLOAD")
    else:
        raise EnvelopeError("INVALID_OLLAMA_OPERATION")
    return f"ollama:{model}"


def _validate_resource_key(value: object, adapter: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise EnvelopeError("INVALID_RESOURCE_KEY")
    if any(character in value for character in "\x00\r\n\t ;&|`$\\"):
        raise EnvelopeError("INVALID_RESOURCE_KEY")
    if not value.startswith(
        {"launchd": "launchd:", "docker-compose": "compose:", "ollama": "ollama:"}[
            adapter
        ]
    ):
        raise EnvelopeError("RESOURCE_ADAPTER_MISMATCH")
    if adapter == "launchd":
        remainder = value.removeprefix("launchd:")
        if ":" not in remainder:
            raise EnvelopeError("INVALID_RESOURCE_KEY")
        domain, label = remainder.rsplit(":", 1)
        _strict_string(domain, DOMAIN_TARGET_RE, "INVALID_RESOURCE_KEY")
        _strict_string(label, SAFE_LABEL_RE, "INVALID_RESOURCE_KEY")
    elif adapter == "docker-compose":
        parts = value.split(":")
        if len(parts) != 3:
            raise EnvelopeError("INVALID_RESOURCE_KEY")
        _strict_string(parts[1], SERVICE_ID_RE, "INVALID_RESOURCE_KEY")
        _strict_string(parts[2], SERVICE_ID_RE, "INVALID_RESOURCE_KEY")
    else:
        _strict_string(
            value.removeprefix("ollama:"), MODEL_RE, "INVALID_RESOURCE_KEY"
        )
    return value


def _validate_operation_payload(
    *,
    adapter: str,
    operation: str,
    resource_key: object,
    argv: object,
    http_request: object,
) -> str:
    resource = _validate_resource_key(resource_key, adapter)
    if operation == "check-readiness":
        if argv is not None or http_request is not None:
            raise EnvelopeError("READINESS_STEP_HAS_ACTION")
        return resource
    if adapter == "launchd":
        if http_request is not None:
            raise EnvelopeError("LAUNCHD_HTTP_FORBIDDEN")
        derived = _launchd_resource(operation, argv)
    elif adapter == "docker-compose":
        if http_request is not None:
            raise EnvelopeError("COMPOSE_HTTP_FORBIDDEN")
        derived = _compose_resource(operation, argv)
    else:
        if argv is not None:
            raise EnvelopeError("OLLAMA_ARGV_FORBIDDEN")
        derived = _ollama_resource(operation, http_request)
    if resource != derived:
        raise EnvelopeError("RESOURCE_KEY_MISMATCH")
    return resource


def _validate_readiness(raw: object, resource_key: str) -> dict[str, object] | None:
    if raw is None:
        return None
    readiness = _exact_object(
        raw,
        frozenset(
            {"kind", "method", "url", "expect", "timeout_ms", "interval_ms"}
        ),
        "INVALID_READINESS_KEYS",
    )
    if readiness.get("kind") != "http" or readiness.get("method") != "GET":
        raise EnvelopeError("INVALID_READINESS_PROBE")
    _loopback_http_url(readiness.get("url"), "UNSAFE_READINESS_URL")
    expect = readiness.get("expect")
    if not isinstance(expect, dict):
        raise EnvelopeError("INVALID_READINESS_EXPECTATION")
    if expect.get("kind") == "status-2xx":
        _exact_object(
            expect, frozenset({"kind"}), "INVALID_READINESS_EXPECTATION"
        )
    elif expect.get("kind") == "ollama-model-resident":
        expected = _exact_object(
            expect,
            frozenset({"kind", "model"}),
            "INVALID_READINESS_EXPECTATION",
        )
        model = _strict_string(
            expected.get("model"), MODEL_RE, "INVALID_OLLAMA_MODEL"
        )
        if resource_key != f"ollama:{model}":
            raise EnvelopeError("READINESS_RESOURCE_MISMATCH")
    else:
        raise EnvelopeError("INVALID_READINESS_EXPECTATION")
    _strict_int(readiness.get("timeout_ms"), "INVALID_READINESS_TIMEOUT", 1, 300_000)
    _strict_int(readiness.get("interval_ms"), "INVALID_READINESS_INTERVAL", 1, 10_000)
    return dict(readiness)


def _validate_rollback(
    raw: object, *, adapter: str, operation: str, resource_key: str
) -> dict[str, object] | None:
    if raw is None:
        return None
    rollback = _exact_object(
        raw,
        frozenset({"operation", "argv", "http_request"}),
        "INVALID_ROLLBACK_KEYS",
    )
    expected_operation = INVERSE_OPERATIONS.get(operation)
    if rollback.get("operation") != expected_operation:
        raise EnvelopeError("ROLLBACK_OPERATION_MISMATCH")
    derived = _validate_operation_payload(
        adapter=adapter,
        operation=str(expected_operation),
        resource_key=resource_key,
        argv=rollback.get("argv"),
        http_request=rollback.get("http_request"),
    )
    if derived != resource_key:
        raise EnvelopeError("ROLLBACK_RESOURCE_MISMATCH")
    return dict(rollback)


def _validate_common_step(
    step: dict[str, object], expected_sequence: int
) -> tuple[str, str, str]:
    if _strict_int(step.get("sequence"), "INVALID_STEP_SEQUENCE", 1, MAX_STEPS) != (
        expected_sequence
    ):
        raise EnvelopeError("NON_CONTIGUOUS_STEP_SEQUENCE")
    adapter = step.get("adapter")
    if adapter not in ADAPTER_OPERATIONS:
        raise EnvelopeError("UNKNOWN_ADAPTER")
    operation = step.get("operation")
    if operation not in ADAPTER_OPERATIONS[adapter]:
        raise EnvelopeError("UNKNOWN_OPERATION")
    service_id = _strict_string(
        step.get("service_id"), SERVICE_ID_RE, "INVALID_STEP_SERVICE_ID"
    )
    return adapter, operation, service_id


def _validate_plan_step(
    raw: object, expected_sequence: int
) -> dict[str, object]:
    step = _exact_object(raw, PLAN_STEP_KEYS, "INVALID_PLAN_STEP_KEYS")
    adapter, operation, service_id = _validate_common_step(step, expected_sequence)
    resource_key = _validate_operation_payload(
        adapter=adapter,
        operation=operation,
        resource_key=step.get("resource_key"),
        argv=step.get("argv"),
        http_request=step.get("http_request"),
    )
    readiness = _validate_readiness(step.get("readiness"), resource_key)
    if operation in {"bootstrap", "kickstart", "start", "load", "check-readiness"} and (
        readiness is None
    ):
        raise EnvelopeError("READINESS_STEP_MISSING_PROBE")
    if operation in {"bootout", "stop", "unload"} and readiness is not None:
        raise EnvelopeError("STOP_STEP_HAS_READINESS")
    rollback = _validate_rollback(
        step.get("rollback"),
        adapter=adapter,
        operation=operation,
        resource_key=resource_key,
    )
    if operation in {"kickstart", "check-readiness"} and rollback is not None:
        raise EnvelopeError("OPERATION_CANNOT_ROLLBACK")
    return {
        "sequence": expected_sequence,
        "service_id": service_id,
        "adapter": adapter,
        "operation": operation,
        "resource_key": resource_key,
        "argv": step.get("argv"),
        "http_request": step.get("http_request"),
        "readiness": readiness,
        "rollback": rollback,
    }


def _validate_intent_sequence(
    steps: list[dict[str, object]], intent: str, target_service_id: str
) -> None:
    grouped: dict[str, list[dict[str, object]]] = {}
    for step in steps:
        grouped.setdefault(str(step["resource_key"]), []).append(step)
    for resource_steps in grouped.values():
        adapter = str(resource_steps[0]["adapter"])
        if any(step["adapter"] != adapter for step in resource_steps):
            raise EnvelopeError("RESOURCE_ADAPTER_CONFLICT")
        service_ids = {str(step["service_id"]) for step in resource_steps}
        if len(service_ids) != 1:
            raise EnvelopeError("RESOURCE_SERVICE_CONFLICT")
        service_id = next(iter(service_ids))
        operations = [str(step["operation"]) for step in resource_steps]
        if intent == "ensure-ready" or (
            intent == "restart" and service_id != target_service_id
        ):
            allowed = {
                "launchd": [["bootstrap"], ["check-readiness"]],
                "docker-compose": [["start"], ["check-readiness"]],
                "ollama": [["load"], ["check-readiness"]],
            }[adapter]
        elif intent == "complete-stop":
            allowed = {
                "launchd": [["bootout"]],
                "docker-compose": [["stop"]],
                "ollama": [["unload"]],
            }[adapter]
        else:
            allowed = {
                "launchd": [["kickstart"]],
                "docker-compose": [["start"], ["stop", "start"]],
                "ollama": [["load"], ["unload", "load"]],
            }[adapter]
        if operations not in allowed:
            raise EnvelopeError("INVALID_INTENT_OPERATION_SEQUENCE")


def compute_plan_digest(plan: Mapping[str, object]) -> str:
    """Compute SHA-256 over the exact plan with ``plan_digest`` omitted."""

    if not isinstance(plan, Mapping):
        raise EnvelopeError("INVALID_PLAN")
    unsigned = dict(plan)
    unsigned.pop("plan_digest", None)
    return _sha256(canonical_json_bytes(unsigned))


def validate_plan(raw: object) -> dict[str, object]:
    """Validate and normalize one typed lifecycle plan."""

    plan = _exact_object(raw, PLAN_KEYS, "INVALID_PLAN_KEYS")
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise EnvelopeError("UNSUPPORTED_PLAN_SCHEMA")
    if plan.get("kind") != "local-ai-adapter-plan":
        raise EnvelopeError("INVALID_PLAN_KIND")
    if plan.get("supervisor_contract_version") != SUPERVISOR_CONTRACT_VERSION:
        raise EnvelopeError("UNSUPPORTED_SUPERVISOR_CONTRACT")
    target = _strict_string(
        plan.get("target_service_id"), SERVICE_ID_RE, "INVALID_TARGET_SERVICE_ID"
    )
    intent = plan.get("intent")
    if intent not in INTENT_OPERATIONS:
        raise EnvelopeError("INVALID_INTENT")
    if plan.get("dry_run") is not True:
        raise EnvelopeError("INVALID_DRY_RUN")
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise EnvelopeError("INVALID_PLAN_STEPS")
    if intent in {"ensure-ready", "restart"} and not steps:
        raise EnvelopeError("EMPTY_ACTIVE_PLAN")

    validated_steps: list[dict[str, object]] = []
    identities: set[tuple[str, str, str]] = set()
    for sequence, raw_step in enumerate(steps, start=1):
        step = _validate_plan_step(raw_step, sequence)
        if step["operation"] not in INTENT_OPERATIONS[intent]:
            raise EnvelopeError("INTENT_OPERATION_MISMATCH")
        identity = (
            str(step["operation"]),
            str(step["resource_key"]),
            str(step["service_id"]),
        )
        if identity in identities:
            raise EnvelopeError("DUPLICATE_PLAN_STEP")
        identities.add(identity)
        validated_steps.append(step)
    _validate_intent_sequence(validated_steps, str(intent), target)
    if validated_steps and target not in {
        str(step["service_id"]) for step in validated_steps
    }:
        raise EnvelopeError("TARGET_NOT_IN_PLAN")

    digest = _strict_string(
        plan.get("plan_digest"), SHA256_RE, "INVALID_PLAN_DIGEST"
    )
    if not hmac.compare_digest(digest, compute_plan_digest(plan)):
        raise EnvelopeError("PLAN_DIGEST_MISMATCH")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "local-ai-adapter-plan",
        "supervisor_contract_version": SUPERVISOR_CONTRACT_VERSION,
        "target_service_id": target,
        "intent": intent,
        "dry_run": plan["dry_run"],
        "steps": validated_steps,
        "plan_digest": digest,
    }


def build_plan(
    *,
    target_service_id: str,
    intent: str,
    dry_run: bool,
    steps: list[dict[str, object]],
) -> dict[str, object]:
    """Build a canonical plan and attach its self-verifying digest."""

    plan: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "local-ai-adapter-plan",
        "supervisor_contract_version": SUPERVISOR_CONTRACT_VERSION,
        "target_service_id": target_service_id,
        "intent": intent,
        "dry_run": dry_run,
        "steps": steps,
    }
    plan["plan_digest"] = compute_plan_digest(plan)
    return validate_plan(plan)


def _plan_scope(
    plan: Mapping[str, object], authorization_phase: str = "apply"
) -> tuple[list[str], list[str]]:
    steps = plan["steps"]
    assert isinstance(steps, list)
    if authorization_phase == "apply":
        scoped = steps
        if not scoped:
            raise PermitRefusal("PLAN_HAS_NO_ACTIONS")
        operations = [str(step["operation"]) for step in scoped]
    elif authorization_phase == "rollback":
        scoped = [step for step in steps if step["rollback"] is not None]
        operations = [str(step["rollback"]["operation"]) for step in scoped]
        if not scoped:
            raise PermitRefusal("PLAN_HAS_NO_ROLLBACK")
    else:
        raise PermitRefusal("INVALID_AUTHORIZATION_PHASE")
    actions = sorted(set(operations))
    adapters = sorted({str(step["adapter"]) for step in scoped})
    return actions, adapters


def validate_result(
    raw: object, expected_plan: object
) -> dict[str, object]:
    """Validate a result against the exact ordered plan and digest."""

    plan = validate_plan(expected_plan)
    result = _exact_object(raw, RESULT_KEYS, "INVALID_RESULT_KEYS")
    if result.get("schema_version") != SCHEMA_VERSION:
        raise EnvelopeError("UNSUPPORTED_RESULT_SCHEMA")
    if result.get("kind") != "local-ai-adapter-result":
        raise EnvelopeError("INVALID_RESULT_KIND")
    if result.get("plan_digest") != plan.get("plan_digest"):
        raise EnvelopeError("RESULT_PLAN_SCOPE_MISMATCH")
    status_value = result.get("status")
    if status_value not in RESULT_OUTCOMES:
        raise EnvelopeError("INVALID_RESULT_STATUS")
    rollback_status = result.get("rollback_status")
    if rollback_status not in ROLLBACK_STATUSES:
        raise EnvelopeError("INVALID_ROLLBACK_STATUS")
    if not isinstance(result.get("readiness_proved"), bool):
        raise EnvelopeError("INVALID_READINESS_PROOF")

    completed = result.get("completed_steps")
    if (
        not isinstance(completed, list)
        or any(isinstance(value, bool) or not isinstance(value, int) for value in completed)
        or completed != sorted(set(completed))
        or any(value < 1 or value > len(plan["steps"]) for value in completed)
        or completed != list(range(1, len(completed) + 1))
    ):
        raise EnvelopeError("INVALID_COMPLETED_STEPS")
    failed_step = result.get("failed_step")
    if failed_step is not None:
        _strict_int(
            failed_step, "INVALID_FAILED_STEP", 1, len(plan["steps"])
        )
        if failed_step in completed:
            raise EnvelopeError("FAILED_STEP_ALREADY_COMPLETED")
    error = result.get("error")
    normalized_error: dict[str, str] | None
    if error is None:
        normalized_error = None
    else:
        error_object = _exact_object(
            error, frozenset({"code", "message"}), "INVALID_RESULT_ERROR"
        )
        code = _strict_string(
            error_object.get("code"), ERROR_CODE_RE, "INVALID_ERROR_CODE"
        )
        message = _strict_string(
            error_object.get("message"),
            ERROR_MESSAGE_RE,
            "INVALID_ERROR_MESSAGE",
        )
        if (
            code not in RESULT_ERROR_MESSAGES
            or message != RESULT_ERROR_MESSAGES[code]
        ):
            raise EnvelopeError("NON_CANONICAL_RESULT_ERROR")
        normalized_error = {"code": code, "message": message}

    if status_value == "dry-run":
        if (
            completed
            or failed_step is not None
            or result["readiness_proved"] is not False
            or rollback_status != "not-run"
            or normalized_error is not None
        ):
            raise EnvelopeError("INCONSISTENT_DRY_RUN_RESULT")
    elif status_value == "succeeded":
        has_readiness = any(
            step["readiness"] is not None for step in plan["steps"]
        )
        if (
            failed_step is not None
            or rollback_status != "not-needed"
            or normalized_error is not None
            or completed != list(range(1, len(plan["steps"]) + 1))
            or result["readiness_proved"] is not has_readiness
        ):
            raise EnvelopeError("PARTIAL_READINESS_CANNOT_SUCCEED")
    elif status_value == "rolled-back":
        if (
            failed_step is None
            or result["readiness_proved"] is not False
            or rollback_status != "succeeded"
            or normalized_error is None
        ):
            raise EnvelopeError("INCONSISTENT_ROLLED_BACK_RESULT")
    elif (
        failed_step is None
        or result["readiness_proved"] is not False
        or rollback_status != "failed"
        or normalized_error is None
    ):
        raise EnvelopeError("ROLLBACK_FAILURE_INCONSISTENT")
    if status_value in {"failed", "rolled-back"}:
        completed_count = len(completed)
        failed_operation = plan["steps"][int(failed_step) - 1]["operation"]
        allowed_failed_steps = {completed_count + 1}
        if failed_operation == "check-readiness" or plan["steps"][
            int(failed_step) - 1
        ]["readiness"] is not None:
            allowed_failed_steps.add(completed_count)
        if failed_step not in allowed_failed_steps:
            raise EnvelopeError("FAILED_STEP_PREFIX_MISMATCH")
    if status_value == "rolled-back":
        noncompensable = {
            int(step["sequence"])
            for step in plan["steps"]
            if step["operation"] != "check-readiness"
            and step["rollback"] is None
        }
        if noncompensable.intersection(completed):
            raise EnvelopeError("NONCOMPENSABLE_STEP_CANNOT_ROLL_BACK")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "local-ai-adapter-result",
        "plan_digest": plan["plan_digest"],
        "status": status_value,
        "completed_steps": list(completed),
        "failed_step": failed_step,
        "readiness_proved": result["readiness_proved"],
        "rollback_status": rollback_status,
        "error": normalized_error,
    }


def permit_signing_bytes(permit: Mapping[str, object]) -> bytes:
    """Return canonical bytes covered by the PM permit signature."""

    if not isinstance(permit, Mapping):
        raise EnvelopeError("INVALID_PERMIT")
    unsigned = dict(permit)
    unsigned.pop("signature", None)
    return canonical_json_bytes(unsigned)


def handoff_receipt_signing_bytes(receipt: Mapping[str, object]) -> bytes:
    """Return canonical bytes covered by the handoff receipt signature."""

    if not isinstance(receipt, Mapping):
        raise EnvelopeError("INVALID_HANDOFF_RECEIPT")
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    return canonical_json_bytes(unsigned)


def validate_handoff_receipt(
    raw: object,
    trusted_receipt_keys: Mapping[str, bytes],
    *,
    expected_target_service_id: str,
    expected_intent: str,
    expected_authorization_phase: str,
    expected_plan_digest: str,
    expected_actions: list[str],
    expected_adapter_set: list[str],
    expected_producer_schema_digest: str,
    expected_catalog_digest: str,
    expected_executor_generation: int,
    expected_state_generation: int,
    expected_verifier_instance_id: str,
    expected_verifier_artifact_digest: str,
    expected_contract_pin_digest: str,
    clock: Callable[[], float] = time.time,
    max_clock_skew_seconds: int = 30,
    max_receipt_lifetime_seconds: int = 60,
) -> dict[str, object]:
    """Authenticate an exact receipt; replay consumption remains broker-owned."""

    receipt = _exact_object(
        raw, HANDOFF_RECEIPT_KEYS, "INVALID_HANDOFF_RECEIPT_KEYS"
    )
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("kind") != "execution-handoff-receipt"
        or receipt.get("receipt_version") != HANDOFF_RECEIPT_VERSION
        or receipt.get("decision") != "AUTHORIZED_FOR_EXECUTOR_HANDOFF"
        or receipt.get("policy_version") != PERMIT_POLICY_VERSION
    ):
        raise PermitRefusal("INVALID_HANDOFF_RECEIPT_VERSION")
    permit_fingerprint = _strict_string(
        receipt.get("permit_fingerprint"),
        SHA256_RE,
        "INVALID_PERMIT_FINGERPRINT",
    )
    if receipt.get("receipt_id") != f"handoff-{permit_fingerprint[:32]}":
        raise PermitRefusal("INVALID_HANDOFF_RECEIPT_ID")
    _strict_string(
        receipt.get("receipt_nonce"), NONCE_RE, "INVALID_RECEIPT_NONCE"
    )
    issued_at = _strict_int(
        receipt.get("issued_at"), "INVALID_RECEIPT_ISSUED_AT", 0, 4_102_444_800
    )
    expires_at = _strict_int(
        receipt.get("expires_at"),
        "INVALID_RECEIPT_EXPIRES_AT",
        0,
        4_102_444_800,
    )
    lifetime = _strict_int(
        max_receipt_lifetime_seconds, "INVALID_RECEIPT_LIFETIME", 1, 300
    )
    skew = _strict_int(max_clock_skew_seconds, "INVALID_CLOCK_SKEW", 0, 300)
    if expires_at <= issued_at or expires_at - issued_at > lifetime:
        raise PermitRefusal("INVALID_HANDOFF_RECEIPT_WINDOW")
    now = int(clock())
    if issued_at > now + skew:
        raise PermitRefusal("HANDOFF_RECEIPT_NOT_YET_VALID")
    if now >= expires_at:
        raise PermitRefusal("STALE_HANDOFF_RECEIPT")
    key_id = _strict_string(
        receipt.get("receipt_key_id"), KEY_ID_RE, "INVALID_RECEIPT_KEY_ID"
    )
    key = trusted_receipt_keys.get(key_id)
    if not isinstance(key, bytes) or len(key) < 32:
        raise PermitRefusal("UNTRUSTED_RECEIPT_KEY")
    signature = _strict_string(
        receipt.get("signature"), SHA256_RE, "INVALID_RECEIPT_SIGNATURE"
    )
    expected_signature = hmac.new(
        key, handoff_receipt_signing_bytes(receipt), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise PermitRefusal("TAMPERED_HANDOFF_RECEIPT")

    if (
        expected_intent not in INTENT_OPERATIONS
        or expected_authorization_phase not in {"apply", "rollback"}
        or expected_actions != sorted(set(expected_actions))
        or any(
            action not in set().union(*ADAPTER_OPERATIONS.values())
            for action in expected_actions
        )
        or expected_adapter_set != sorted(set(expected_adapter_set))
        or any(
            adapter not in ADAPTER_OPERATIONS for adapter in expected_adapter_set
        )
    ):
        raise ValueError("invalid expected handoff scope")
    expected_scope = {
        "target_service_id": _strict_string(
            expected_target_service_id,
            SERVICE_ID_RE,
            "INVALID_EXPECTED_SERVICE_ID",
        ),
        "intent": expected_intent,
        "authorization_phase": expected_authorization_phase,
        "plan_digest": _strict_string(
            expected_plan_digest, SHA256_RE, "INVALID_EXPECTED_PLAN_DIGEST"
        ),
        "actions": expected_actions,
        "adapter_set": expected_adapter_set,
        "producer_schema_digest": _strict_string(
            expected_producer_schema_digest,
            SHA256_RE,
            "INVALID_EXPECTED_PRODUCER_SCHEMA_DIGEST",
        ),
        "catalog_digest": _strict_string(
            expected_catalog_digest,
            SHA256_RE,
            "INVALID_EXPECTED_CATALOG_DIGEST",
        ),
        "executor_generation": _strict_int(
            expected_executor_generation,
            "INVALID_EXPECTED_EXECUTOR_GENERATION",
            1,
            2**63 - 1,
        ),
        "state_generation": _strict_int(
            expected_state_generation,
            "INVALID_EXPECTED_STATE_GENERATION",
            1,
            2**63 - 1,
        ),
        "verifier_instance_id": _strict_string(
            expected_verifier_instance_id,
            SAFE_TOKEN_RE,
            "INVALID_EXPECTED_VERIFIER_INSTANCE",
        ),
        "verifier_artifact_digest": _strict_string(
            expected_verifier_artifact_digest,
            SHA256_RE,
            "INVALID_EXPECTED_VERIFIER_ARTIFACT_DIGEST",
        ),
        "contract_pin_digest": _strict_string(
            expected_contract_pin_digest,
            SHA256_RE,
            "INVALID_EXPECTED_CONTRACT_PIN_DIGEST",
        ),
        "rollback_authorized": expected_authorization_phase == "rollback",
    }
    if any(receipt.get(field) != value for field, value in expected_scope.items()):
        raise PermitRefusal("WRONG_HANDOFF_RECEIPT_SCOPE")
    _strict_string(receipt.get("permit_id"), SAFE_TOKEN_RE, "INVALID_PERMIT_ID")
    return dict(receipt)


class AuthorizationTelemetry:
    """Bounded content-free permit decisions; no nonce, key, path, or payload."""

    def __init__(self, limit: int = 512):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4096:
            raise ValueError("telemetry limit must be between 1 and 4096")
        self._events: deque[dict[str, object]] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def record(
        self,
        *,
        outcome: str,
        reason_code: str,
        plan: Mapping[str, object],
        adapter_set: list[str],
        authorization_phase: str,
    ) -> None:
        if (
            outcome not in {"REFUSED", "AUTHORIZED_FOR_EXECUTOR_HANDOFF"}
            or not TELEMETRY_REASON_RE.fullmatch(reason_code)
            or plan.get("intent") not in INTENT_OPERATIONS
            or not isinstance(plan.get("target_service_id"), str)
            or not SERVICE_ID_RE.fullmatch(str(plan["target_service_id"]))
            or not isinstance(plan.get("plan_digest"), str)
            or not SHA256_RE.fullmatch(str(plan["plan_digest"]))
            or authorization_phase not in {"apply", "rollback"}
            or adapter_set != sorted(set(adapter_set))
            or any(adapter not in ADAPTER_OPERATIONS for adapter in adapter_set)
        ):
            raise ValueError("authorization telemetry must be content-free")
        event = {
            "schema_version": SCHEMA_VERSION,
            "event": "execution-permit-verification",
            "outcome": outcome,
            "reason_code": reason_code,
            "target_service_id": plan["target_service_id"],
            "intent": plan["intent"],
            "authorization_phase": authorization_phase,
            "plan_digest": plan["plan_digest"],
            "adapter_set": list(adapter_set),
        }
        with self._lock:
            self._events.append(event)

    def events(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(event) for event in self._events]


class PermitVerifier:
    """Verify PM permits and atomically consume each nonce exactly once."""

    def __init__(
        self,
        state_path: str | Path,
        trusted_keys: Mapping[str, bytes],
        *,
        expected_producer_schema_digest: str,
        expected_catalog_digest: str,
        expected_executor_generation: int,
        expected_state_generation: int,
        expected_plan_digests: Mapping[tuple[str, str], str],
        clock: Callable[[], float] = time.time,
        max_clock_skew_seconds: int = 30,
        max_permit_lifetime_seconds: int = 300,
        receipt_key_id: str,
        receipt_signing_key: bytes,
        verifier_instance_id: str,
        verifier_artifact_digest: str,
        contract_pin_digest: str,
        receipt_lifetime_seconds: int = 60,
        telemetry: AuthorizationTelemetry | None = None,
    ):
        self.state_path = Path(state_path)
        if not self.state_path.is_absolute():
            raise PermitStateError("STATE_PATH_MUST_BE_ABSOLUTE")
        self.clock = clock
        self.expected_producer_schema_digest = _strict_string(
            expected_producer_schema_digest,
            SHA256_RE,
            "INVALID_PRODUCER_SCHEMA_DIGEST",
        )
        self.expected_catalog_digest = _strict_string(
            expected_catalog_digest, SHA256_RE, "INVALID_CATALOG_DIGEST"
        )
        self.expected_executor_generation = _strict_int(
            expected_executor_generation, "INVALID_EXECUTOR_GENERATION", 1, 2**63 - 1
        )
        self.expected_state_generation = _strict_int(
            expected_state_generation, "INVALID_STATE_GENERATION", 1, 2**63 - 1
        )
        self.expected_plan_digests: dict[tuple[str, str], str] = {}
        for scope, digest in expected_plan_digests.items():
            if (
                not isinstance(scope, tuple)
                or len(scope) != 2
                or not isinstance(scope[0], str)
                or not isinstance(scope[1], str)
            ):
                raise ValueError("expected plan scope must be a service/intent tuple")
            service_id = _strict_string(
                scope[0], SERVICE_ID_RE, "INVALID_EXPECTED_PLAN_SERVICE"
            )
            if scope[1] not in INTENT_OPERATIONS:
                raise ValueError("expected plan intent is invalid")
            plan_digest = _strict_string(
                digest, SHA256_RE, "INVALID_EXPECTED_PLAN_DIGEST"
            )
            self.expected_plan_digests[(service_id, scope[1])] = plan_digest
        if not self.expected_plan_digests:
            raise ValueError("at least one catalog-derived plan digest is required")
        self.max_clock_skew_seconds = _strict_int(
            max_clock_skew_seconds, "INVALID_CLOCK_SKEW", 0, 300
        )
        self.max_permit_lifetime_seconds = _strict_int(
            max_permit_lifetime_seconds, "INVALID_PERMIT_LIFETIME", 1, 3600
        )
        self.receipt_lifetime_seconds = _strict_int(
            receipt_lifetime_seconds, "INVALID_RECEIPT_LIFETIME", 1, 300
        )
        self.receipt_key_id = _strict_string(
            receipt_key_id, KEY_ID_RE, "INVALID_RECEIPT_KEY_ID"
        )
        if not isinstance(receipt_signing_key, bytes) or len(receipt_signing_key) < 32:
            raise ValueError("receipt signing key must be at least 32 bytes")
        self._receipt_signing_key = bytes(receipt_signing_key)
        self.verifier_instance_id = _strict_string(
            verifier_instance_id, SAFE_TOKEN_RE, "INVALID_VERIFIER_INSTANCE_ID"
        )
        self.verifier_artifact_digest = _strict_string(
            verifier_artifact_digest,
            SHA256_RE,
            "INVALID_VERIFIER_ARTIFACT_DIGEST",
        )
        self.contract_pin_digest = _strict_string(
            contract_pin_digest, SHA256_RE, "INVALID_CONTRACT_PIN_DIGEST"
        )
        self.telemetry = telemetry or AuthorizationTelemetry()
        self._trusted_keys: dict[str, bytes] = {}
        for key_id, key in trusted_keys.items():
            _strict_string(key_id, KEY_ID_RE, "INVALID_KEY_ID")
            if not isinstance(key, bytes) or len(key) < 32:
                raise ValueError("trusted permit keys must be at least 32 bytes")
            self._trusted_keys[key_id] = bytes(key)
        if not self._trusted_keys:
            raise ValueError("at least one trusted permit key is required")
        if any(
            hmac.compare_digest(self._receipt_signing_key, permit_key)
            for permit_key in self._trusted_keys.values()
        ):
            raise ValueError("receipt and PM permit keys must be distinct")
        self._initialize()

    def _after_nonce_recorded(self) -> None:
        """Test seam for proving rollback before commit; production is a no-op."""

    def _build_handoff_receipt(
        self,
        *,
        plan: Mapping[str, object],
        permit: Mapping[str, object],
        permit_digest: str,
        authorization_phase: str,
        actions: list[str],
        adapters: list[str],
    ) -> dict[str, object]:
        issued_at = int(self.clock())
        expires_at = min(
            int(permit["expires_at"]),
            issued_at + self.receipt_lifetime_seconds,
        )
        if expires_at <= issued_at:
            raise PermitRefusal("HANDOFF_RECEIPT_WINDOW_EXPIRED")
        receipt_nonce = base64.urlsafe_b64encode(
            hmac.new(
                self._receipt_signing_key,
                b"execution-handoff-receipt-nonce\x00"
                + permit_digest.encode("ascii"),
                hashlib.sha256,
            ).digest()
        ).rstrip(b"=").decode("ascii")
        _strict_string(
            receipt_nonce, NONCE_RE, "INVALID_RECEIPT_NONCE"
        )
        receipt: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "kind": "execution-handoff-receipt",
            "receipt_version": HANDOFF_RECEIPT_VERSION,
            "decision": "AUTHORIZED_FOR_EXECUTOR_HANDOFF",
            "policy_version": PERMIT_POLICY_VERSION,
            "receipt_id": f"handoff-{permit_digest[:32]}",
            "receipt_nonce": receipt_nonce,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "verifier_instance_id": self.verifier_instance_id,
            "receipt_key_id": self.receipt_key_id,
            "target_service_id": plan["target_service_id"],
            "intent": plan["intent"],
            "authorization_phase": authorization_phase,
            "plan_digest": plan["plan_digest"],
            "actions": actions,
            "adapter_set": adapters,
            "permit_id": permit["permit_id"],
            "permit_fingerprint": permit_digest,
            "producer_schema_digest": self.expected_producer_schema_digest,
            "catalog_digest": self.expected_catalog_digest,
            "executor_generation": self.expected_executor_generation,
            "state_generation": self.expected_state_generation,
            "verifier_artifact_digest": self.verifier_artifact_digest,
            "contract_pin_digest": self.contract_pin_digest,
            "rollback_authorized": authorization_phase == "rollback",
        }
        receipt["signature"] = hmac.new(
            self._receipt_signing_key,
            handoff_receipt_signing_bytes(receipt),
            hashlib.sha256,
        ).hexdigest()
        return receipt

    def _preflight_state_path(self) -> None:
        try:
            info = self.state_path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise PermitStateError("STATE_PATH_UNREADABLE") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise PermitStateError("UNSAFE_STATE_PATH")
        if info.st_size > MAX_STATE_BYTES:
            raise PermitStateError("STATE_FILE_TOO_LARGE")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise PermitStateError("UNSAFE_STATE_PERMISSIONS")

    def _prepare_state_path(self) -> None:
        try:
            current = Path(self.state_path.anchor)
            for part in self.state_path.parent.parts[1:]:
                current = current / part
                if current.exists() and current.is_symlink():
                    raise PermitStateError("UNSAFE_STATE_PARENT")
            self.state_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            if self.state_path.parent.is_symlink():
                raise PermitStateError("UNSAFE_STATE_PARENT")
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(
                self.state_path,
                flags,
                0o600,
            )
        except FileExistsError:
            self._preflight_state_path()
            return
        except PermitStateError:
            raise
        except OSError as exc:
            raise PermitStateError("STATE_CREATE_FAILED") from exc
        else:
            os.close(descriptor)
        self._preflight_state_path()

    def _connect(self) -> sqlite3.Connection:
        self._prepare_state_path()
        try:
            connection = sqlite3.connect(
                self.state_path,
                timeout=5,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise PermitStateError("STATE_OPEN_FAILED") from exc

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            check = connection.execute("PRAGMA quick_check").fetchone()
            if check is None or check[0] != "ok":
                raise PermitStateError("STATE_INTEGRITY_FAILED")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, 1}:
                raise PermitStateError("UNSUPPORTED_STATE_VERSION")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS permit_uses (
                    nonce_hash TEXT PRIMARY KEY,
                    permit_digest TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,
                    target_service_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    authorization_phase TEXT NOT NULL,
                    adapter_set_json TEXT NOT NULL,
                    producer_schema_digest TEXT NOT NULL,
                    catalog_digest TEXT NOT NULL,
                    executor_generation INTEGER NOT NULL,
                    state_generation INTEGER NOT NULL,
                    policy_version TEXT NOT NULL,
                    consumed_at INTEGER NOT NULL,
                    UNIQUE (
                        plan_digest,
                        authorization_phase,
                        catalog_digest,
                        executor_generation,
                        state_generation
                    )
                ) STRICT
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS revocations (
                    nonce_hash TEXT PRIMARY KEY,
                    revoked_at INTEGER NOT NULL,
                    reason_code TEXT NOT NULL
                ) STRICT
                """
            )
            connection.execute("PRAGMA user_version = 1")
            connection.execute("COMMIT")
        except PermitStateError:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise PermitStateError("STATE_INITIALIZATION_FAILED") from exc
        finally:
            connection.close()

    def _validate_permit(
        self,
        raw: object,
        plan: Mapping[str, object],
        authorization_phase: str,
    ) -> tuple[dict[str, object], str, str]:
        permit = _exact_object(raw, PERMIT_KEYS, "INVALID_PERMIT_KEYS")
        if permit.get("schema_version") != SCHEMA_VERSION:
            raise PermitRefusal("UNSUPPORTED_PERMIT_SCHEMA")
        if permit.get("kind") != "execution-permit":
            raise PermitRefusal("INVALID_PERMIT_KIND")
        if permit.get("policy_version") != PERMIT_POLICY_VERSION:
            raise PermitRefusal("WRONG_POLICY_VERSION")
        _strict_string(
            permit.get("permit_id"), SAFE_TOKEN_RE, "INVALID_PERMIT_ID"
        )
        if permit.get("authorization_phase") != authorization_phase:
            raise PermitRefusal("WRONG_AUTHORIZATION_PHASE")
        issued_at = _strict_int(
            permit.get("issued_at"), "INVALID_ISSUED_AT", 0, 4_102_444_800
        )
        expires_at = _strict_int(
            permit.get("expires_at"), "INVALID_EXPIRES_AT", 0, 4_102_444_800
        )
        if expires_at <= issued_at or (
            expires_at - issued_at > self.max_permit_lifetime_seconds
        ):
            raise PermitRefusal("INVALID_PERMIT_WINDOW")
        now = int(self.clock())
        if issued_at > now + self.max_clock_skew_seconds:
            raise PermitRefusal("PERMIT_NOT_YET_VALID")
        if now >= expires_at:
            raise PermitRefusal("STALE_PERMIT")

        nonce = _strict_string(permit.get("nonce"), NONCE_RE, "INVALID_NONCE")
        key_id = _strict_string(permit.get("key_id"), KEY_ID_RE, "INVALID_KEY_ID")
        key = self._trusted_keys.get(key_id)
        if key is None:
            raise PermitRefusal("UNTRUSTED_KEY")
        signature = _strict_string(
            permit.get("signature"), SHA256_RE, "INVALID_SIGNATURE"
        )
        expected_signature = hmac.new(
            key, permit_signing_bytes(permit), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise PermitRefusal("TAMPERED_PERMIT")

        actions, adapters = _plan_scope(plan, authorization_phase)
        for key_name in ("plan_digest", "target_service_id", "intent"):
            if permit.get(key_name) != plan.get(key_name):
                raise PermitRefusal("WRONG_PERMIT_SCOPE")
        if permit.get("actions") != actions or permit.get("adapter_set") != adapters:
            raise PermitRefusal("WRONG_PERMIT_SCOPE")
        if (
            permit.get("producer_schema_digest")
            != self.expected_producer_schema_digest
            or permit.get("catalog_digest") != self.expected_catalog_digest
            or permit.get("executor_generation") != self.expected_executor_generation
            or permit.get("state_generation") != self.expected_state_generation
        ):
            raise PermitRefusal("WRONG_AUTHORITY_GENERATION")

        normalized = dict(permit)
        permit_digest = _sha256(canonical_json_bytes(normalized))
        nonce_hash = _sha256(nonce.encode("ascii"))
        return normalized, permit_digest, nonce_hash

    def verify_and_consume(
        self,
        raw_plan: object,
        raw_permit: object,
        *,
        authorization_phase: str = "apply",
    ) -> dict[str, object]:
        """Return an authorization handoff or fail closed without execution."""

        plan = validate_plan(raw_plan)
        actions, adapters = _plan_scope(plan, authorization_phase)
        try:
            expected_digest = self.expected_plan_digests.get(
                (str(plan["target_service_id"]), str(plan["intent"]))
            )
            if expected_digest is None or not hmac.compare_digest(
                expected_digest, str(plan["plan_digest"])
            ):
                raise PermitRefusal("PLAN_NOT_CATALOG_DERIVED")
            permit, permit_digest, nonce_hash = self._validate_permit(
                raw_permit, plan, authorization_phase
            )
            receipt = self._build_handoff_receipt(
                plan=plan,
                permit=permit,
                permit_digest=permit_digest,
                authorization_phase=authorization_phase,
                actions=actions,
                adapters=adapters,
            )
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                revoked = connection.execute(
                    "SELECT 1 FROM revocations WHERE nonce_hash = ?",
                    (nonce_hash,),
                ).fetchone()
                if revoked is not None:
                    raise PermitRefusal("REVOKED_PERMIT")
                existing = connection.execute(
                    """
                    SELECT permit_digest
                    FROM permit_uses
                    WHERE nonce_hash = ?
                    """,
                    (nonce_hash,),
                ).fetchone()
                if existing is not None:
                    if existing["permit_digest"] != permit_digest:
                        raise PermitRefusal("CONFLICTING_PERMIT")
                    raise PermitRefusal("REPLAYED_PERMIT")
                conflicting = connection.execute(
                    """
                    SELECT 1
                    FROM permit_uses
                    WHERE plan_digest = ?
                      AND authorization_phase = ?
                      AND catalog_digest = ?
                      AND executor_generation = ?
                      AND state_generation = ?
                    """,
                    (
                        plan["plan_digest"],
                        authorization_phase,
                        self.expected_catalog_digest,
                        self.expected_executor_generation,
                        self.expected_state_generation,
                    ),
                ).fetchone()
                if conflicting is not None:
                    raise PermitRefusal("CONFLICTING_PERMIT")
                connection.execute(
                    """
                    INSERT INTO permit_uses (
                        nonce_hash, permit_digest, plan_digest,
                        target_service_id, intent, authorization_phase,
                        adapter_set_json, producer_schema_digest,
                        catalog_digest, executor_generation, state_generation,
                        policy_version, consumed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        nonce_hash,
                        permit_digest,
                        plan["plan_digest"],
                        plan["target_service_id"],
                        plan["intent"],
                        authorization_phase,
                        canonical_json_bytes(adapters).decode("ascii"),
                        self.expected_producer_schema_digest,
                        self.expected_catalog_digest,
                        self.expected_executor_generation,
                        self.expected_state_generation,
                        PERMIT_POLICY_VERSION,
                        int(self.clock()),
                    ),
                )
                self._after_nonce_recorded()
                connection.execute("COMMIT")
            except PermitRefusal:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except Exception as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                if isinstance(exc, PermitStateError):
                    raise
                raise PermitStateError("NONCE_CONSUMPTION_FAILED") from exc
            finally:
                connection.close()
        except (EnvelopeError, PermitRefusal, PermitStateError) as exc:
            self.telemetry.record(
                outcome="REFUSED",
                reason_code=exc.code,
                plan=plan,
                adapter_set=adapters,
                authorization_phase=authorization_phase,
            )
            raise

        self.telemetry.record(
            outcome="AUTHORIZED_FOR_EXECUTOR_HANDOFF",
            reason_code="PERMIT_CONSUMED",
            plan=plan,
            adapter_set=adapters,
            authorization_phase=authorization_phase,
        )
        return receipt

    def revoke(self, nonce: str, *, reason_code: str = "policy-revoked") -> None:
        """Persist an idempotent deny for one nonce before or after use."""

        nonce_value = _strict_string(nonce, NONCE_RE, "INVALID_NONCE")
        if reason_code not in {"policy-revoked", "key-compromise", "scope-withdrawn"}:
            raise EnvelopeError("INVALID_REVOCATION_REASON")
        nonce_hash = _sha256(nonce_value.encode("ascii"))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO revocations (nonce_hash, revoked_at, reason_code)
                VALUES (?, ?, ?)
                ON CONFLICT(nonce_hash) DO NOTHING
                """,
                (nonce_hash, int(self.clock()), reason_code),
            )
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise PermitStateError("REVOCATION_FAILED") from exc
        finally:
            connection.close()

    def deterministic_snapshot_bytes(self) -> bytes:
        """Return a stable, privacy-bounded representation of durable state."""

        connection = self._connect()
        try:
            uses = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT nonce_hash, permit_digest, plan_digest,
                           target_service_id, intent, authorization_phase,
                           adapter_set_json, producer_schema_digest,
                           catalog_digest, executor_generation,
                           state_generation,
                           policy_version, consumed_at
                    FROM permit_uses
                    ORDER BY nonce_hash
                    """
                )
            ]
            for row in uses:
                row["adapter_set"] = json.loads(row.pop("adapter_set_json"))
            revocations = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT nonce_hash, revoked_at, reason_code
                    FROM revocations
                    ORDER BY nonce_hash
                    """
                )
            ]
        except (json.JSONDecodeError, sqlite3.Error) as exc:
            raise PermitStateError("STATE_SNAPSHOT_FAILED") from exc
        finally:
            connection.close()
        return canonical_json_bytes(
            {
                "schema_version": SCHEMA_VERSION,
                "permit_uses": uses,
                "revocations": revocations,
            }
        )
