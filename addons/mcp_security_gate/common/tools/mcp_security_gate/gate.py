"""The evaluator: a declared risk manifest -> findings + fail-closed disposition.

This module performs no I/O and never imports or executes anything a manifest
names. It runs the closed set of static checks in a deterministic order and
computes an overall disposition that FAILS CLOSED: the gate allows only when
every applicable check passes; any FAIL verdict (including every
missing/unknown/degraded posture, which the checks map to FAIL) blocks.
"""

from __future__ import annotations

from typing import Tuple

from .checks import SERVER_CHECKS, TOOL_CHECKS
from .contracts import (
    Disposition,
    Finding,
    GateReport,
    RiskManifest,
    Verdict,
)


def evaluate_findings(manifest: RiskManifest) -> Tuple[Finding, ...]:
    """Run every closed-set check in a stable order and return the findings."""

    findings = []
    for server_check in SERVER_CHECKS:
        findings.append(server_check(manifest))
    for tool in manifest.tools:
        for tool_check in TOOL_CHECKS:
            findings.append(tool_check(tool))
    return tuple(findings)


def evaluate(manifest: RiskManifest) -> GateReport:
    findings = evaluate_findings(manifest)
    # Fail-closed disposition: a single FAIL anywhere blocks the whole server.
    # NOT_APPLICABLE verdicts never allow on their own and never block.
    disposition = (
        Disposition.BLOCK
        if any(finding.verdict is Verdict.FAIL for finding in findings)
        else Disposition.ALLOW
    )
    return GateReport(
        server_id=manifest.server_id,
        disposition=disposition,
        fail_closed=True,
        findings=findings,
    )


def evaluate_contract_dict(value: dict) -> GateReport:
    """Parse a static manifest object and evaluate it. Never executes it."""

    manifest = RiskManifest.from_contract_dict(value)
    return evaluate(manifest)
