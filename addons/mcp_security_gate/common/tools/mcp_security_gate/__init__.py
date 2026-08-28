"""Source-only, offline MCP-server security gate over a declared risk manifest."""

from .contracts import (
    AnnotationHandling,
    CheckId,
    DegradedBehavior,
    Disposition,
    Finding,
    GateReport,
    Posture,
    ReasonCode,
    RiskManifest,
    ToolEffect,
    ToolManifest,
    TokenPosture,
    Reversibility,
    Verdict,
)
from .gate import evaluate, evaluate_contract_dict, evaluate_findings

__all__ = [
    "AnnotationHandling",
    "CheckId",
    "DegradedBehavior",
    "Disposition",
    "Finding",
    "GateReport",
    "Posture",
    "ReasonCode",
    "Reversibility",
    "RiskManifest",
    "ToolEffect",
    "ToolManifest",
    "TokenPosture",
    "Verdict",
    "evaluate",
    "evaluate_contract_dict",
    "evaluate_findings",
]

__version__ = "0.1.0"
