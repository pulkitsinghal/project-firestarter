from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..contracts import (
    AnnotationHandling,
    DegradedBehavior,
    Posture,
    Reversibility,
    RiskManifest,
    ToolEffect,
    ToolManifest,
    TokenPosture,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def tool(
    *,
    tool_id: str = "tool-a",
    effect: ToolEffect = ToolEffect.READ_ONLY,
    reversibility: Reversibility = Reversibility.READ_ONLY,
    requires_confirmation: bool = False,
    annotation_handling: AnnotationHandling = AnnotationHandling.TREATED_AS_DATA,
    output_sanitization: Posture = Posture.ENFORCED,
    timeout_ms: Optional[int] = 3000,
    rate_limit_per_minute: Optional[int] = 60,
    max_response_bytes: Optional[int] = 65536,
) -> ToolManifest:
    return ToolManifest(
        tool_id=tool_id,
        effect=effect,
        reversibility=reversibility,
        requires_confirmation=requires_confirmation,
        annotation_handling=annotation_handling,
        output_sanitization=output_sanitization,
        timeout_ms=timeout_ms,
        rate_limit_per_minute=rate_limit_per_minute,
        max_response_bytes=max_response_bytes,
    )


def manifest(
    *,
    server_id: str = "srv-a",
    token_posture: TokenPosture = TokenPosture.AUDIENCE_BOUND,
    granted_audience_id: str = "aud-app",
    upstream_audience_id: str = "aud-app",
    secret_log_posture: Posture = Posture.ENFORCED,
    degraded_behavior: DegradedBehavior = DegradedBehavior.FAIL_CLOSED,
    tools: tuple[ToolManifest, ...] | None = None,
) -> RiskManifest:
    return RiskManifest(
        server_id=server_id,
        token_posture=token_posture,
        granted_audience_id=granted_audience_id,
        upstream_audience_id=upstream_audience_id,
        secret_log_posture=secret_log_posture,
        degraded_behavior=degraded_behavior,
        tools=tools if tools is not None else (tool(),),
    )
