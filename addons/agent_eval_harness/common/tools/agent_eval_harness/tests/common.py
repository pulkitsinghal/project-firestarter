from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ..contracts import (
    AdvisoryCritique,
    CandidateOutput,
    canonical_digest,
    Check,
    CheckKind,
    CritiqueVerdict,
    EvalCase,
    Evidence,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Sentinel used inside the synthetic fixture so no sha256 digest is hand-copied:
# the loader recomputes the correct digest from the adjacent values. A vector
# that must exercise a digest mismatch supplies a real (wrong) sha256 instead.
AUTO = "AUTO"


def digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def check(
    *,
    check_id: str = "chk-1",
    kind: CheckKind = CheckKind.EXACT_EQUALS,
    blocking: bool = True,
    evidence_id: str = "ev-1",
    field_token: str = "answer",
    params: dict | None = None,
) -> Check:
    if params is None:
        params = {"expected": "north"}
    return Check(
        check_id=check_id,
        kind=kind,
        blocking=blocking,
        evidence_id=evidence_id,
        field_token=field_token,
        params=params,
    )


def evidence(
    *,
    evidence_id: str = "ev-1",
    values: dict | None = None,
    digest_override: str | None = None,
) -> Evidence:
    if values is None:
        values = {"answer": "north"}
    resolved = digest_override or canonical_digest(values)
    return Evidence(evidence_id=evidence_id, digest=resolved, values=values)


def case(
    *,
    case_id: str = "case-1",
    input_fixture_id: str = "fixture-1",
    input_fixture_digest: str | None = None,
    checks: tuple[Check, ...] | None = None,
) -> EvalCase:
    if checks is None:
        checks = (check(),)
    return EvalCase(
        case_id=case_id,
        input_fixture_id=input_fixture_id,
        input_fixture_digest=input_fixture_digest or digest("input-1"),
        checks=checks,
    )


def candidate(
    *,
    case_id: str = "case-1",
    evidence_items: tuple[Evidence, ...] | None = None,
    critique: AdvisoryCritique | None = None,
) -> CandidateOutput:
    if evidence_items is None:
        evidence_items = (evidence(),)
    return CandidateOutput(
        case_id=case_id, evidence=evidence_items, critique=critique
    )


def critique(
    *,
    critique_id: str = "crit-1",
    verdict: CritiqueVerdict = CritiqueVerdict.PASS,
    note_token: str = "advisory-note",
) -> AdvisoryCritique:
    return AdvisoryCritique(
        critique_id=critique_id, verdict=verdict, note_token=note_token
    )


def input_fixtures_for(a_case: EvalCase, values: dict) -> dict:
    """A one-entry input-fixture map whose digest matches the case ref, so the
    reducer treats the required input as present."""

    return {a_case.input_fixture_id: values}


def load_case_vectors() -> list[dict]:
    """Load synthetic scoring vectors, resolving AUTO digests deterministically.

    Each vector: {id, expectedState, inputFixtures, case, candidate}. Returns a
    list of {id, expected_state, case: EvalCase, candidate: CandidateOutput,
    input_fixtures: dict}."""

    raw = json.loads(
        (FIXTURE_DIR / "eval-cases.synthetic.json").read_text(encoding="utf-8")
    )
    vectors: list[dict] = []
    for vector in raw["vectors"]:
        input_fixtures = copy.deepcopy(vector["inputFixtures"])
        case_dict = copy.deepcopy(vector["case"])
        candidate_dict = copy.deepcopy(vector["candidate"])

        # Resolve the input-fixture ref digest.
        ref = case_dict["inputFixtureRef"]
        if ref["digest"] == AUTO:
            values = input_fixtures.get(ref["fixtureId"])
            if values is None:
                raise AssertionError(f"{vector['id']}: AUTO input ref has no values")
            ref["digest"] = canonical_digest(values)

        # Resolve each evidence digest.
        for item in candidate_dict["evidence"]:
            if item["digest"] == AUTO:
                item["digest"] = canonical_digest(item["values"])

        vectors.append(
            {
                "id": vector["id"],
                "expected_state": vector["expectedState"],
                "input_fixtures": input_fixtures,
                "case": EvalCase.from_contract_dict(case_dict),
                "candidate": CandidateOutput.from_contract_dict(candidate_dict),
            }
        )
    return vectors
