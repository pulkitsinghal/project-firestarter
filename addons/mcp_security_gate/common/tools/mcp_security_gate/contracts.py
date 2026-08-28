"""Closed, content-minimized types for the offline MCP-server security gate.

Real endpoints, credentials, tokens, request/response bodies, log lines, and
prompt text are deliberately absent. A declaring operator translates an MCP
server's runtime posture into policy-owned opaque IDs and finite enums before
this boundary. The gate reasons only over that declared, static manifest; it
never imports, connects to, or executes anything the manifest names.

The design derives its checks from neutral public concepts only: the Model
Context Protocol's public notions of tools, tool annotations, and structured
output; JSON Schema 2020-12 closed-object validation; and NIST/OWASP-style
control concepts (least privilege, confused-deputy avoidance, output encoding,
secret hygiene, resource bounding, and fail-closed degraded behavior).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Optional, Tuple


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

MAX_TOOLS = 64


def require_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be an opaque identifier")


class ToolEffect(str, Enum):
    READ_ONLY = "read-only"
    IDEMPOTENT_WRITE = "idempotent-write"
    EXTERNAL_SEND = "external-send"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


class Reversibility(str, Enum):
    READ_ONLY = "read-only"
    REVERSIBLE = "reversible"
    COMPENSATING = "compensating"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


class AnnotationHandling(str, Enum):
    TREATED_AS_DATA = "treated-as-data"
    TRUSTED_AS_INSTRUCTIONS = "trusted-as-instructions"
    UNKNOWN = "unknown"


class Posture(str, Enum):
    ENFORCED = "enforced"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class TokenPosture(str, Enum):
    AUDIENCE_BOUND = "audience-bound"
    BLIND_PASSTHROUGH = "blind-passthrough"
    UNKNOWN = "unknown"


class DegradedBehavior(str, Enum):
    FAIL_CLOSED = "fail-closed"
    FAIL_OPEN = "fail-open"
    UNKNOWN = "unknown"


class CheckId(str, Enum):
    EFFECT_SOUNDNESS = "effect-soundness"
    CONFIRMATION_REQUIRED = "confirmation-required"
    UNTRUSTED_ANNOTATION_HANDLING = "untrusted-annotation-handling"
    TOKEN_AUDIENCE = "token-audience"
    OUTPUT_SANITIZATION = "output-sanitization"
    SECRET_LEAKAGE = "secret-leakage"
    TIMEOUT_PRESENT = "timeout-present"
    RATE_LIMIT_PRESENT = "rate-limit-present"
    SIZE_CAP_PRESENT = "size-cap-present"
    DEGRADED_FAIL_CLOSED = "degraded-fail-closed"


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not-applicable"


class Disposition(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"


class ReasonCode(str, Enum):
    # effect-soundness
    EFFECT_DECLARED_AND_BOUNDED = "effect-declared-and-bounded"
    EFFECT_UNDECLARED = "effect-undeclared"
    EFFECT_REVERSIBILITY_MISMATCH = "effect-reversibility-mismatch"
    # confirmation-required
    CONFIRMATION_PRESENT = "confirmation-present"
    CONFIRMATION_MISSING_FOR_IRREVERSIBLE = "confirmation-missing-for-irreversible"
    CONFIRMATION_NOT_REQUIRED = "confirmation-not-required"
    # untrusted-annotation-handling
    ANNOTATIONS_TREATED_AS_DATA = "annotations-treated-as-data"
    ANNOTATIONS_TRUSTED_AS_INSTRUCTIONS = "annotations-trusted-as-instructions"
    ANNOTATION_POSTURE_UNKNOWN = "annotation-posture-unknown"
    # token-audience
    TOKEN_AUDIENCE_BOUND = "token-audience-bound"
    TOKEN_BLIND_PASSTHROUGH = "token-blind-passthrough"
    TOKEN_AUDIENCE_MISMATCH = "token-audience-mismatch"
    TOKEN_POSTURE_UNKNOWN = "token-posture-unknown"
    # output-sanitization
    OUTPUT_SANITIZED = "output-sanitized"
    OUTPUT_UNSANITIZED = "output-unsanitized"
    OUTPUT_POSTURE_UNKNOWN = "output-posture-unknown"
    # secret-leakage
    SECRETS_REDACTED = "secrets-redacted"
    SECRET_IN_LOGS = "secret-in-logs"
    SECRET_POSTURE_UNKNOWN = "secret-posture-unknown"
    # timeout-present
    TIMEOUT_BOUNDED = "timeout-bounded"
    TIMEOUT_ABSENT = "timeout-absent"
    # rate-limit-present
    RATE_LIMIT_BOUNDED = "rate-limit-bounded"
    RATE_LIMIT_ABSENT = "rate-limit-absent"
    # size-cap-present
    SIZE_CAP_BOUNDED = "size-cap-bounded"
    SIZE_CAP_ABSENT = "size-cap-absent"
    # degraded-fail-closed
    DEGRADED_FAILS_CLOSED = "degraded-fails-closed"
    DEGRADED_FAILS_OPEN = "degraded-fails-open"
    DEGRADED_POSTURE_UNKNOWN = "degraded-posture-unknown"


def canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolManifest:
    tool_id: str
    effect: ToolEffect
    reversibility: Reversibility
    requires_confirmation: bool
    annotation_handling: AnnotationHandling
    output_sanitization: Posture
    timeout_ms: Optional[int]
    rate_limit_per_minute: Optional[int]
    max_response_bytes: Optional[int]

    def __post_init__(self) -> None:
        require_id(self.tool_id, "tool_id")
        if not isinstance(self.effect, ToolEffect):
            raise ValueError("effect must be a ToolEffect")
        if not isinstance(self.reversibility, Reversibility):
            raise ValueError("reversibility must be a Reversibility")
        if not isinstance(self.requires_confirmation, bool):
            raise ValueError("requires_confirmation must be a bool")
        if not isinstance(self.annotation_handling, AnnotationHandling):
            raise ValueError("annotation_handling must be an AnnotationHandling")
        if not isinstance(self.output_sanitization, Posture):
            raise ValueError("output_sanitization must be a Posture")
        for field, value in (
            ("timeout_ms", self.timeout_ms),
            ("rate_limit_per_minute", self.rate_limit_per_minute),
            ("max_response_bytes", self.max_response_bytes),
        ):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"{field} must be an integer or null")
            if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                raise ValueError(f"{field} must be non-negative")

    def to_contract_dict(self) -> dict:
        return {
            "toolId": self.tool_id,
            "effect": self.effect.value,
            "reversibility": self.reversibility.value,
            "requiresConfirmation": self.requires_confirmation,
            "annotationHandling": self.annotation_handling.value,
            "outputSanitization": self.output_sanitization.value,
            "timeoutMs": self.timeout_ms,
            "rateLimitPerMinute": self.rate_limit_per_minute,
            "maxResponseBytes": self.max_response_bytes,
        }

    @classmethod
    def from_contract_dict(cls, value: dict) -> "ToolManifest":
        expected = {
            "toolId",
            "effect",
            "reversibility",
            "requiresConfirmation",
            "annotationHandling",
            "outputSanitization",
            "timeoutMs",
            "rateLimitPerMinute",
            "maxResponseBytes",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("tool manifest fields do not match schema 1.0")
        return cls(
            tool_id=value["toolId"],
            effect=ToolEffect(value["effect"]),
            reversibility=Reversibility(value["reversibility"]),
            requires_confirmation=_require_bool(value["requiresConfirmation"]),
            annotation_handling=AnnotationHandling(value["annotationHandling"]),
            output_sanitization=Posture(value["outputSanitization"]),
            timeout_ms=_require_opt_int(value["timeoutMs"], "timeoutMs"),
            rate_limit_per_minute=_require_opt_int(
                value["rateLimitPerMinute"], "rateLimitPerMinute"
            ),
            max_response_bytes=_require_opt_int(
                value["maxResponseBytes"], "maxResponseBytes"
            ),
        )


def _require_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected a boolean value")
    return value


def _require_opt_int(value: object, field: str) -> Optional[int]:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer or null")
    return value


@dataclass(frozen=True, slots=True)
class RiskManifest:
    server_id: str
    token_posture: TokenPosture
    granted_audience_id: str
    upstream_audience_id: str
    secret_log_posture: Posture
    degraded_behavior: DegradedBehavior
    tools: Tuple[ToolManifest, ...]

    def __post_init__(self) -> None:
        require_id(self.server_id, "server_id")
        require_id(self.granted_audience_id, "granted_audience_id")
        require_id(self.upstream_audience_id, "upstream_audience_id")
        if not isinstance(self.token_posture, TokenPosture):
            raise ValueError("token_posture must be a TokenPosture")
        if not isinstance(self.secret_log_posture, Posture):
            raise ValueError("secret_log_posture must be a Posture")
        if not isinstance(self.degraded_behavior, DegradedBehavior):
            raise ValueError("degraded_behavior must be a DegradedBehavior")
        if not self.tools or len(self.tools) > MAX_TOOLS:
            raise ValueError("tool set must be non-empty and bounded")
        tool_ids = [tool.tool_id for tool in self.tools]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("tool IDs must be unique")

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "serverId": self.server_id,
            "tokenPosture": self.token_posture.value,
            "grantedAudienceId": self.granted_audience_id,
            "upstreamAudienceId": self.upstream_audience_id,
            "secretLogPosture": self.secret_log_posture.value,
            "degradedBehavior": self.degraded_behavior.value,
            "tools": [tool.to_contract_dict() for tool in self.tools],
        }

    @property
    def manifest_digest(self) -> str:
        return canonical_digest(self.to_contract_dict())

    @classmethod
    def from_contract_dict(cls, value: dict) -> "RiskManifest":
        expected = {
            "schemaVersion",
            "serverId",
            "tokenPosture",
            "grantedAudienceId",
            "upstreamAudienceId",
            "secretLogPosture",
            "degradedBehavior",
            "tools",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("risk manifest fields do not match schema 1.0")
        if value["schemaVersion"] != "1.0":
            raise ValueError("unsupported risk manifest schema")
        if not isinstance(value["tools"], list):
            raise ValueError("tools must be a list")
        return cls(
            server_id=value["serverId"],
            token_posture=TokenPosture(value["tokenPosture"]),
            granted_audience_id=value["grantedAudienceId"],
            upstream_audience_id=value["upstreamAudienceId"],
            secret_log_posture=Posture(value["secretLogPosture"]),
            degraded_behavior=DegradedBehavior(value["degradedBehavior"]),
            tools=tuple(ToolManifest.from_contract_dict(item) for item in value["tools"]),
        )


@dataclass(frozen=True, slots=True)
class Finding:
    check_id: CheckId
    subject_id: str
    verdict: Verdict
    reason_code: ReasonCode

    def __post_init__(self) -> None:
        require_id(self.subject_id, "subject_id")
        if not isinstance(self.check_id, CheckId):
            raise ValueError("check_id must be a CheckId")
        if not isinstance(self.verdict, Verdict):
            raise ValueError("verdict must be a Verdict")
        if not isinstance(self.reason_code, ReasonCode):
            raise ValueError("reason_code must be a ReasonCode")

    def to_contract_dict(self) -> dict:
        return {
            "checkId": self.check_id.value,
            "subjectId": self.subject_id,
            "verdict": self.verdict.value,
            "reasonCode": self.reason_code.value,
        }


@dataclass(frozen=True, slots=True)
class GateReport:
    server_id: str
    disposition: Disposition
    fail_closed: bool
    findings: Tuple[Finding, ...]

    def __post_init__(self) -> None:
        require_id(self.server_id, "server_id")
        if not isinstance(self.disposition, Disposition):
            raise ValueError("disposition must be a Disposition")
        if not isinstance(self.fail_closed, bool):
            raise ValueError("fail_closed must be a bool")

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "serverId": self.server_id,
            "disposition": self.disposition.value,
            "failClosed": self.fail_closed,
            "findings": [finding.to_contract_dict() for finding in self.findings],
        }
