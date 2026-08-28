"""Deterministic, pure per-risk static checks over a declared risk manifest.

Every function is a total, side-effect-free mapping from declared posture to a
single typed Finding. There is no I/O, no dynamic import, and no execution of
anything the manifest names. Each check fails closed: a missing, unknown, or
degraded posture yields a FAIL verdict, never a PASS.
"""

from __future__ import annotations

from .contracts import (
    AnnotationHandling,
    CheckId,
    DegradedBehavior,
    Finding,
    Posture,
    ReasonCode,
    RiskManifest,
    ToolEffect,
    ToolManifest,
    TokenPosture,
    Verdict,
    Reversibility,
)


# Effects whose runtime action cannot be silently undone. Confirmation is
# mandatory for these, mirroring least-privilege / human-in-the-loop control
# concepts.
_CONFIRMATION_EFFECTS = frozenset({ToolEffect.EXTERNAL_SEND, ToolEffect.DESTRUCTIVE})

# Bounded reversibility envelope permitted for each declared effect. Anything
# outside the envelope is an unsound (over-broad) effect declaration.
_EFFECT_REVERSIBILITY = {
    ToolEffect.READ_ONLY: frozenset({Reversibility.READ_ONLY}),
    ToolEffect.IDEMPOTENT_WRITE: frozenset(
        {Reversibility.REVERSIBLE, Reversibility.COMPENSATING}
    ),
    ToolEffect.EXTERNAL_SEND: frozenset(
        {Reversibility.COMPENSATING, Reversibility.IRREVERSIBLE}
    ),
    ToolEffect.DESTRUCTIVE: frozenset({Reversibility.IRREVERSIBLE}),
}


def check_effect_soundness(tool: ToolManifest) -> Finding:
    if tool.effect is ToolEffect.UNKNOWN or tool.reversibility is Reversibility.UNKNOWN:
        return Finding(
            CheckId.EFFECT_SOUNDNESS,
            tool.tool_id,
            Verdict.FAIL,
            ReasonCode.EFFECT_UNDECLARED,
        )
    allowed = _EFFECT_REVERSIBILITY[tool.effect]
    if tool.reversibility not in allowed:
        return Finding(
            CheckId.EFFECT_SOUNDNESS,
            tool.tool_id,
            Verdict.FAIL,
            ReasonCode.EFFECT_REVERSIBILITY_MISMATCH,
        )
    return Finding(
        CheckId.EFFECT_SOUNDNESS,
        tool.tool_id,
        Verdict.PASS,
        ReasonCode.EFFECT_DECLARED_AND_BOUNDED,
    )


def _confirmation_required(tool: ToolManifest) -> bool:
    # Fail closed: an unknown effect or reversibility is treated as if it could
    # be irreversible, so confirmation is demanded.
    if tool.effect is ToolEffect.UNKNOWN or tool.reversibility is Reversibility.UNKNOWN:
        return True
    return (
        tool.effect in _CONFIRMATION_EFFECTS
        or tool.reversibility is Reversibility.IRREVERSIBLE
    )


def check_confirmation_required(tool: ToolManifest) -> Finding:
    if not _confirmation_required(tool):
        return Finding(
            CheckId.CONFIRMATION_REQUIRED,
            tool.tool_id,
            Verdict.NOT_APPLICABLE,
            ReasonCode.CONFIRMATION_NOT_REQUIRED,
        )
    if tool.requires_confirmation:
        return Finding(
            CheckId.CONFIRMATION_REQUIRED,
            tool.tool_id,
            Verdict.PASS,
            ReasonCode.CONFIRMATION_PRESENT,
        )
    return Finding(
        CheckId.CONFIRMATION_REQUIRED,
        tool.tool_id,
        Verdict.FAIL,
        ReasonCode.CONFIRMATION_MISSING_FOR_IRREVERSIBLE,
    )


def check_untrusted_annotation_handling(tool: ToolManifest) -> Finding:
    if tool.annotation_handling is AnnotationHandling.TREATED_AS_DATA:
        return Finding(
            CheckId.UNTRUSTED_ANNOTATION_HANDLING,
            tool.tool_id,
            Verdict.PASS,
            ReasonCode.ANNOTATIONS_TREATED_AS_DATA,
        )
    if tool.annotation_handling is AnnotationHandling.TRUSTED_AS_INSTRUCTIONS:
        return Finding(
            CheckId.UNTRUSTED_ANNOTATION_HANDLING,
            tool.tool_id,
            Verdict.FAIL,
            ReasonCode.ANNOTATIONS_TRUSTED_AS_INSTRUCTIONS,
        )
    return Finding(
        CheckId.UNTRUSTED_ANNOTATION_HANDLING,
        tool.tool_id,
        Verdict.FAIL,
        ReasonCode.ANNOTATION_POSTURE_UNKNOWN,
    )


def check_output_sanitization(tool: ToolManifest) -> Finding:
    if tool.output_sanitization is Posture.ENFORCED:
        return Finding(
            CheckId.OUTPUT_SANITIZATION,
            tool.tool_id,
            Verdict.PASS,
            ReasonCode.OUTPUT_SANITIZED,
        )
    if tool.output_sanitization is Posture.ABSENT:
        return Finding(
            CheckId.OUTPUT_SANITIZATION,
            tool.tool_id,
            Verdict.FAIL,
            ReasonCode.OUTPUT_UNSANITIZED,
        )
    return Finding(
        CheckId.OUTPUT_SANITIZATION,
        tool.tool_id,
        Verdict.FAIL,
        ReasonCode.OUTPUT_POSTURE_UNKNOWN,
    )


def check_timeout_present(tool: ToolManifest) -> Finding:
    if tool.timeout_ms is not None and tool.timeout_ms > 0:
        return Finding(
            CheckId.TIMEOUT_PRESENT,
            tool.tool_id,
            Verdict.PASS,
            ReasonCode.TIMEOUT_BOUNDED,
        )
    return Finding(
        CheckId.TIMEOUT_PRESENT,
        tool.tool_id,
        Verdict.FAIL,
        ReasonCode.TIMEOUT_ABSENT,
    )


def check_rate_limit_present(tool: ToolManifest) -> Finding:
    if tool.rate_limit_per_minute is not None and tool.rate_limit_per_minute > 0:
        return Finding(
            CheckId.RATE_LIMIT_PRESENT,
            tool.tool_id,
            Verdict.PASS,
            ReasonCode.RATE_LIMIT_BOUNDED,
        )
    return Finding(
        CheckId.RATE_LIMIT_PRESENT,
        tool.tool_id,
        Verdict.FAIL,
        ReasonCode.RATE_LIMIT_ABSENT,
    )


def check_size_cap_present(tool: ToolManifest) -> Finding:
    if tool.max_response_bytes is not None and tool.max_response_bytes > 0:
        return Finding(
            CheckId.SIZE_CAP_PRESENT,
            tool.tool_id,
            Verdict.PASS,
            ReasonCode.SIZE_CAP_BOUNDED,
        )
    return Finding(
        CheckId.SIZE_CAP_PRESENT,
        tool.tool_id,
        Verdict.FAIL,
        ReasonCode.SIZE_CAP_ABSENT,
    )


def check_token_audience(manifest: RiskManifest) -> Finding:
    if manifest.token_posture is TokenPosture.BLIND_PASSTHROUGH:
        return Finding(
            CheckId.TOKEN_AUDIENCE,
            manifest.server_id,
            Verdict.FAIL,
            ReasonCode.TOKEN_BLIND_PASSTHROUGH,
        )
    if manifest.token_posture is TokenPosture.UNKNOWN:
        return Finding(
            CheckId.TOKEN_AUDIENCE,
            manifest.server_id,
            Verdict.FAIL,
            ReasonCode.TOKEN_POSTURE_UNKNOWN,
        )
    if manifest.upstream_audience_id != manifest.granted_audience_id:
        return Finding(
            CheckId.TOKEN_AUDIENCE,
            manifest.server_id,
            Verdict.FAIL,
            ReasonCode.TOKEN_AUDIENCE_MISMATCH,
        )
    return Finding(
        CheckId.TOKEN_AUDIENCE,
        manifest.server_id,
        Verdict.PASS,
        ReasonCode.TOKEN_AUDIENCE_BOUND,
    )


def check_secret_leakage(manifest: RiskManifest) -> Finding:
    if manifest.secret_log_posture is Posture.ENFORCED:
        return Finding(
            CheckId.SECRET_LEAKAGE,
            manifest.server_id,
            Verdict.PASS,
            ReasonCode.SECRETS_REDACTED,
        )
    if manifest.secret_log_posture is Posture.ABSENT:
        return Finding(
            CheckId.SECRET_LEAKAGE,
            manifest.server_id,
            Verdict.FAIL,
            ReasonCode.SECRET_IN_LOGS,
        )
    return Finding(
        CheckId.SECRET_LEAKAGE,
        manifest.server_id,
        Verdict.FAIL,
        ReasonCode.SECRET_POSTURE_UNKNOWN,
    )


def check_degraded_fail_closed(manifest: RiskManifest) -> Finding:
    if manifest.degraded_behavior is DegradedBehavior.FAIL_CLOSED:
        return Finding(
            CheckId.DEGRADED_FAIL_CLOSED,
            manifest.server_id,
            Verdict.PASS,
            ReasonCode.DEGRADED_FAILS_CLOSED,
        )
    if manifest.degraded_behavior is DegradedBehavior.FAIL_OPEN:
        return Finding(
            CheckId.DEGRADED_FAIL_CLOSED,
            manifest.server_id,
            Verdict.FAIL,
            ReasonCode.DEGRADED_FAILS_OPEN,
        )
    return Finding(
        CheckId.DEGRADED_FAIL_CLOSED,
        manifest.server_id,
        Verdict.FAIL,
        ReasonCode.DEGRADED_POSTURE_UNKNOWN,
    )


# Server-scoped checks run once per manifest; tool-scoped checks run per tool.
SERVER_CHECKS = (
    check_token_audience,
    check_secret_leakage,
    check_degraded_fail_closed,
)

TOOL_CHECKS = (
    check_effect_soundness,
    check_confirmation_required,
    check_untrusted_annotation_handling,
    check_output_sanitization,
    check_timeout_present,
    check_rate_limit_present,
    check_size_cap_present,
)
