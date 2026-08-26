"""Closed, content-minimized types for a deterministic agent-eval harness.

Raw prompts, model responses, transcripts, credentials, hosts, and private
records are deliberately absent. A stamped project translates those details
into opaque IDs, content-addressed digests, and small synthetic values before
they cross this boundary. Every type here fails closed on unknown fields,
unknown enum members, and out-of-bound values so a malformed case or candidate
can never be scored.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Mapping, Optional, Tuple, Union


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

MAX_CHECKS = 64
MAX_EVIDENCE = 64
MAX_FIELDS = 64
MAX_LIST = 128
MAX_STRING = 1024
MAX_PATTERN = 200

# A JSON scalar or a bounded list of JSON scalars. No nested objects: values
# that cross the boundary are already reduced to comparable primitives.
Scalar = Union[str, int, float, bool]


def require_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be an opaque identifier")


def require_digest(value: str, field: str) -> None:
    if not isinstance(value, str) or not SAFE_DIGEST.fullmatch(value):
        raise ValueError(f"{field} must be a sha256 digest")


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _check_scalar(value: object, field: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            raise ValueError(f"{field} string exceeds bound")
        return
    raise ValueError(f"{field} must be a JSON scalar")


def _check_value(value: object, field: str) -> None:
    """A boundary value is a scalar or a bounded list of scalars."""

    if isinstance(value, list):
        if len(value) > MAX_LIST:
            raise ValueError(f"{field} list exceeds bound")
        for item in value:
            _check_scalar(item, field)
        return
    _check_scalar(value, field)


class CheckKind(str, Enum):
    """Closed vocabulary of deterministic, in-process, stdlib-only checks."""

    EXACT_EQUALS = "exact-equals"
    SUBSET = "subset"
    REGEX_MATCH = "regex-match"
    NUMERIC_THRESHOLD = "numeric-threshold"
    ORDERED_CONTAINS = "ordered-contains"


class NumericComparator(str, Enum):
    GE = "ge"
    LE = "le"
    GT = "gt"
    LT = "lt"
    EQ = "eq"


class CheckOutcome(str, Enum):
    """Per-check result. SATISFIED/VIOLATED are computed; UNAVAILABLE means a
    required evidence value was missing or its digest did not verify."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNAVAILABLE = "unavailable"


class ResultState(str, Enum):
    """Closed set of terminal verdicts. Blocking checks alone decide
    PASSED/FAILED; NEEDS_REVIEW is a non-blocking signal only; UNAVAILABLE
    means a required input or evidence value was missing."""

    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    UNAVAILABLE = "unavailable"


class CritiqueVerdict(str, Enum):
    """Advisory-only. Recorded, never authoritative for scoring."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


def _validate_params(kind: CheckKind, params: Mapping[str, object]) -> dict:
    if not isinstance(params, dict):
        raise ValueError("check params must be an object")
    keys = set(params)
    if kind in (CheckKind.EXACT_EQUALS, CheckKind.SUBSET, CheckKind.ORDERED_CONTAINS):
        if keys != {"expected"}:
            raise ValueError(f"{kind.value} params must have exactly the key 'expected'")
        expected = params["expected"]
        if kind is CheckKind.EXACT_EQUALS:
            _check_value(expected, "expected")
        else:
            if not isinstance(expected, list):
                raise ValueError(f"{kind.value} expected must be a list")
            _check_value(expected, "expected")
        normalized = {"expected": expected}
    elif kind is CheckKind.REGEX_MATCH:
        if keys != {"pattern"}:
            raise ValueError("regex-match params must be exactly {pattern}")
        pattern = params["pattern"]
        if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN:
            raise ValueError("regex-match pattern must be a bounded non-empty string")
        try:
            re.compile(pattern)
        except re.error as exc:  # fail closed on an uncompilable pattern
            raise ValueError(f"regex-match pattern does not compile: {exc}") from exc
        normalized = {"pattern": pattern}
    elif kind is CheckKind.NUMERIC_THRESHOLD:
        if keys != {"comparator", "bound"}:
            raise ValueError("numeric-threshold params must be {comparator, bound}")
        comparator = NumericComparator(params["comparator"])
        bound = params["bound"]
        if isinstance(bound, bool) or not isinstance(bound, (int, float)):
            raise ValueError("numeric-threshold bound must be a number")
        normalized = {"comparator": comparator.value, "bound": bound}
    else:  # unreachable: CheckKind is closed
        raise ValueError("unknown check kind")
    return normalized


@dataclass(frozen=True)
class Check:
    check_id: str
    kind: CheckKind
    blocking: bool
    evidence_id: str
    field_token: str
    params: dict

    def __post_init__(self) -> None:
        require_id(self.check_id, "check_id")
        require_id(self.evidence_id, "evidence_id")
        require_id(self.field_token, "field_token")
        if not isinstance(self.blocking, bool):
            raise ValueError("blocking must be a boolean")
        object.__setattr__(self, "params", _validate_params(self.kind, self.params))

    def to_contract_dict(self) -> dict:
        return {
            "checkId": self.check_id,
            "kind": self.kind.value,
            "blocking": self.blocking,
            "evidenceId": self.evidence_id,
            "fieldToken": self.field_token,
            "params": dict(self.params),
        }

    @classmethod
    def from_contract_dict(cls, value: object) -> "Check":
        expected = {"checkId", "kind", "blocking", "evidenceId", "fieldToken", "params"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("check fields do not match schema 1.0")
        return cls(
            check_id=value["checkId"],
            kind=CheckKind(value["kind"]),
            blocking=value["blocking"],
            evidence_id=value["evidenceId"],
            field_token=value["fieldToken"],
            params=value["params"],
        )


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    input_fixture_id: str
    input_fixture_digest: str
    checks: Tuple[Check, ...]

    def __post_init__(self) -> None:
        require_id(self.case_id, "case_id")
        require_id(self.input_fixture_id, "input_fixture_id")
        require_digest(self.input_fixture_digest, "input_fixture_digest")
        if not self.checks or len(self.checks) > MAX_CHECKS:
            raise ValueError("case must declare between 1 and MAX_CHECKS checks")
        ids = [check.check_id for check in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("check ids must be unique within a case")

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "caseId": self.case_id,
            "inputFixtureRef": {
                "fixtureId": self.input_fixture_id,
                "digest": self.input_fixture_digest,
            },
            "checks": [check.to_contract_dict() for check in self.checks],
        }

    @classmethod
    def from_contract_dict(cls, value: object) -> "EvalCase":
        expected = {"schemaVersion", "caseId", "inputFixtureRef", "checks"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("eval case fields do not match schema 1.0")
        if value["schemaVersion"] != "1.0":
            raise ValueError("unsupported eval case schema")
        ref = value["inputFixtureRef"]
        if not isinstance(ref, dict) or set(ref) != {"fixtureId", "digest"}:
            raise ValueError("inputFixtureRef fields do not match schema 1.0")
        checks = value["checks"]
        if not isinstance(checks, list):
            raise ValueError("checks must be a list")
        return cls(
            case_id=value["caseId"],
            input_fixture_id=ref["fixtureId"],
            input_fixture_digest=ref["digest"],
            checks=tuple(Check.from_contract_dict(item) for item in checks),
        )


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    digest: str
    values: dict

    def __post_init__(self) -> None:
        require_id(self.evidence_id, "evidence_id")
        require_digest(self.digest, "digest")
        if not isinstance(self.values, dict) or len(self.values) > MAX_FIELDS:
            raise ValueError("evidence values must be a bounded object")
        for token, item in self.values.items():
            require_id(token, "field_token")
            _check_value(item, token)

    @property
    def computed_digest(self) -> str:
        return canonical_digest(self.values)

    @property
    def verified(self) -> bool:
        return self.digest == self.computed_digest

    def to_contract_dict(self) -> dict:
        return {
            "evidenceId": self.evidence_id,
            "digest": self.digest,
            "values": dict(self.values),
        }

    @classmethod
    def from_contract_dict(cls, value: object) -> "Evidence":
        expected = {"evidenceId", "digest", "values"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("evidence fields do not match schema 1.0")
        return cls(
            evidence_id=value["evidenceId"],
            digest=value["digest"],
            values=value["values"],
        )


@dataclass(frozen=True)
class AdvisoryCritique:
    """A quarantined, model-authored advisory annotation. The reducer records
    it verbatim and NEVER consults it while scoring (see harness.evaluate)."""

    critique_id: str
    verdict: CritiqueVerdict
    note_token: str

    def __post_init__(self) -> None:
        require_id(self.critique_id, "critique_id")
        require_id(self.note_token, "note_token")

    def to_contract_dict(self) -> dict:
        return {
            "critiqueId": self.critique_id,
            "verdict": self.verdict.value,
            "noteToken": self.note_token,
        }

    @classmethod
    def from_contract_dict(cls, value: object) -> "AdvisoryCritique":
        expected = {"critiqueId", "verdict", "noteToken"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("advisory critique fields do not match schema 1.0")
        return cls(
            critique_id=value["critiqueId"],
            verdict=CritiqueVerdict(value["verdict"]),
            note_token=value["noteToken"],
        )


@dataclass(frozen=True)
class CandidateOutput:
    case_id: str
    evidence: Tuple[Evidence, ...]
    critique: Optional[AdvisoryCritique] = None

    def __post_init__(self) -> None:
        require_id(self.case_id, "case_id")
        if len(self.evidence) > MAX_EVIDENCE:
            raise ValueError("evidence set exceeds bound")
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence ids must be unique")

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "caseId": self.case_id,
            "evidence": [item.to_contract_dict() for item in self.evidence],
            "advisoryCritique": (
                self.critique.to_contract_dict() if self.critique is not None else None
            ),
        }

    @classmethod
    def from_contract_dict(cls, value: object) -> "CandidateOutput":
        expected = {"schemaVersion", "caseId", "evidence", "advisoryCritique"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("candidate output fields do not match schema 1.0")
        if value["schemaVersion"] != "1.0":
            raise ValueError("unsupported candidate output schema")
        evidence = value["evidence"]
        if not isinstance(evidence, list):
            raise ValueError("evidence must be a list")
        critique_value = value["advisoryCritique"]
        return cls(
            case_id=value["caseId"],
            evidence=tuple(Evidence.from_contract_dict(item) for item in evidence),
            critique=(
                AdvisoryCritique.from_contract_dict(critique_value)
                if critique_value is not None
                else None
            ),
        )


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    kind: CheckKind
    blocking: bool
    outcome: CheckOutcome

    def to_contract_dict(self) -> dict:
        return {
            "checkId": self.check_id,
            "kind": self.kind.value,
            "blocking": self.blocking,
            "outcome": self.outcome.value,
        }


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    state: ResultState
    check_results: Tuple[CheckResult, ...]
    evidence_verified: bool
    advisory_critique_recorded: bool

    def _scored_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "caseId": self.case_id,
            "state": self.state.value,
            "checkResults": [item.to_contract_dict() for item in self.check_results],
            "evidenceVerified": self.evidence_verified,
            "advisoryCritiqueRecorded": self.advisory_critique_recorded,
        }

    @property
    def result_digest(self) -> str:
        return canonical_digest(self._scored_dict())

    def to_contract_dict(self) -> dict:
        payload = self._scored_dict()
        payload["resultDigest"] = self.result_digest
        return payload
