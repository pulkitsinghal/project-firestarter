from __future__ import annotations

import unittest

from ..checks import (
    check_confirmation_required,
    check_degraded_fail_closed,
    check_effect_soundness,
    check_output_sanitization,
    check_rate_limit_present,
    check_secret_leakage,
    check_size_cap_present,
    check_timeout_present,
    check_token_audience,
    check_untrusted_annotation_handling,
)
from ..contracts import (
    AnnotationHandling,
    CheckId,
    DegradedBehavior,
    Posture,
    ReasonCode,
    Reversibility,
    ToolEffect,
    TokenPosture,
    Verdict,
)
from .common import manifest, tool


class EffectSoundnessTests(unittest.TestCase):
    def test_bounded_effect_passes(self) -> None:
        finding = check_effect_soundness(
            tool(effect=ToolEffect.DESTRUCTIVE, reversibility=Reversibility.IRREVERSIBLE)
        )
        self.assertIs(finding.check_id, CheckId.EFFECT_SOUNDNESS)
        self.assertIs(finding.verdict, Verdict.PASS)
        self.assertIs(finding.reason_code, ReasonCode.EFFECT_DECLARED_AND_BOUNDED)

    def test_unknown_effect_fails_undeclared(self) -> None:
        finding = check_effect_soundness(
            tool(effect=ToolEffect.UNKNOWN, reversibility=Reversibility.UNKNOWN)
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.EFFECT_UNDECLARED)

    def test_destructive_marked_reversible_is_mismatch(self) -> None:
        finding = check_effect_soundness(
            tool(effect=ToolEffect.DESTRUCTIVE, reversibility=Reversibility.REVERSIBLE)
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.EFFECT_REVERSIBILITY_MISMATCH)


class ConfirmationTests(unittest.TestCase):
    def test_read_only_is_not_applicable(self) -> None:
        finding = check_confirmation_required(tool())
        self.assertIs(finding.verdict, Verdict.NOT_APPLICABLE)
        self.assertIs(finding.reason_code, ReasonCode.CONFIRMATION_NOT_REQUIRED)

    def test_irreversible_without_confirmation_fails(self) -> None:
        finding = check_confirmation_required(
            tool(
                effect=ToolEffect.DESTRUCTIVE,
                reversibility=Reversibility.IRREVERSIBLE,
                requires_confirmation=False,
            )
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(
            finding.reason_code, ReasonCode.CONFIRMATION_MISSING_FOR_IRREVERSIBLE
        )

    def test_unknown_effect_demands_confirmation(self) -> None:
        finding = check_confirmation_required(
            tool(
                effect=ToolEffect.UNKNOWN,
                reversibility=Reversibility.UNKNOWN,
                requires_confirmation=False,
            )
        )
        self.assertIs(finding.verdict, Verdict.FAIL)


class AnnotationTests(unittest.TestCase):
    def test_treated_as_data_passes(self) -> None:
        finding = check_untrusted_annotation_handling(tool())
        self.assertIs(finding.verdict, Verdict.PASS)

    def test_trusted_annotations_fail(self) -> None:
        finding = check_untrusted_annotation_handling(
            tool(annotation_handling=AnnotationHandling.TRUSTED_AS_INSTRUCTIONS)
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(
            finding.reason_code, ReasonCode.ANNOTATIONS_TRUSTED_AS_INSTRUCTIONS
        )

    def test_unknown_annotation_posture_fails_closed(self) -> None:
        finding = check_untrusted_annotation_handling(
            tool(annotation_handling=AnnotationHandling.UNKNOWN)
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.ANNOTATION_POSTURE_UNKNOWN)


class ResourceBoundTests(unittest.TestCase):
    def test_output_unknown_fails_closed(self) -> None:
        finding = check_output_sanitization(tool(output_sanitization=Posture.UNKNOWN))
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.OUTPUT_POSTURE_UNKNOWN)

    def test_missing_timeout_fails(self) -> None:
        finding = check_timeout_present(tool(timeout_ms=None))
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.TIMEOUT_ABSENT)

    def test_zero_timeout_is_not_bounded(self) -> None:
        finding = check_timeout_present(tool(timeout_ms=0))
        self.assertIs(finding.verdict, Verdict.FAIL)

    def test_missing_rate_limit_fails(self) -> None:
        finding = check_rate_limit_present(tool(rate_limit_per_minute=None))
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.RATE_LIMIT_ABSENT)

    def test_missing_size_cap_fails(self) -> None:
        finding = check_size_cap_present(tool(max_response_bytes=None))
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.SIZE_CAP_ABSENT)


class ServerPostureTests(unittest.TestCase):
    def test_blind_passthrough_fails(self) -> None:
        finding = check_token_audience(
            manifest(token_posture=TokenPosture.BLIND_PASSTHROUGH)
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.TOKEN_BLIND_PASSTHROUGH)

    def test_audience_mismatch_is_confused_deputy(self) -> None:
        finding = check_token_audience(
            manifest(granted_audience_id="aud-app", upstream_audience_id="aud-other")
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.TOKEN_AUDIENCE_MISMATCH)

    def test_unknown_token_posture_fails_closed(self) -> None:
        finding = check_token_audience(manifest(token_posture=TokenPosture.UNKNOWN))
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.TOKEN_POSTURE_UNKNOWN)

    def test_secret_absent_fails(self) -> None:
        finding = check_secret_leakage(manifest(secret_log_posture=Posture.ABSENT))
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.SECRET_IN_LOGS)

    def test_degraded_fail_open_fails(self) -> None:
        finding = check_degraded_fail_closed(
            manifest(degraded_behavior=DegradedBehavior.FAIL_OPEN)
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.DEGRADED_FAILS_OPEN)

    def test_degraded_unknown_fails_closed(self) -> None:
        finding = check_degraded_fail_closed(
            manifest(degraded_behavior=DegradedBehavior.UNKNOWN)
        )
        self.assertIs(finding.verdict, Verdict.FAIL)
        self.assertIs(finding.reason_code, ReasonCode.DEGRADED_POSTURE_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
