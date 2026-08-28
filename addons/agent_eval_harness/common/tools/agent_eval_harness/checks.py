"""Deterministic, pure, stdlib-only blocking-check implementations.

Each function maps (observed value, params) to a CheckOutcome. Functions never
read the clock, the network, the filesystem, or any global; they never call
eval/exec and never import a caller-named module. A missing observed value is
resolved to UNAVAILABLE by the reducer before these run; here a present value
of the wrong shape for the check is a genuine VIOLATED (the candidate produced
a malformed answer), never an exception.
"""

from __future__ import annotations

import re
from typing import Callable, Dict

from .contracts import CheckKind, CheckOutcome, NumericComparator


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _hashable_scalars(items: list) -> bool:
    return all(isinstance(item, (str, int, float, bool)) for item in items)


def exact_equals(observed: object, params: dict) -> CheckOutcome:
    return (
        CheckOutcome.SATISFIED
        if observed == params["expected"]
        else CheckOutcome.VIOLATED
    )


def subset(observed: object, params: dict) -> CheckOutcome:
    expected = params["expected"]
    if not isinstance(observed, list) or not _hashable_scalars(observed):
        return CheckOutcome.VIOLATED
    if set(expected).issubset(set(observed)):
        return CheckOutcome.SATISFIED
    return CheckOutcome.VIOLATED


def regex_match(observed: object, params: dict) -> CheckOutcome:
    if not isinstance(observed, str):
        return CheckOutcome.VIOLATED
    # Pattern was compiled once at case construction; fullmatch keeps the rubric
    # unambiguous. re operates on the bounded observed string only.
    if re.fullmatch(params["pattern"], observed) is not None:
        return CheckOutcome.SATISFIED
    return CheckOutcome.VIOLATED


def numeric_threshold(observed: object, params: dict) -> CheckOutcome:
    if not _is_number(observed):
        return CheckOutcome.VIOLATED
    comparator = NumericComparator(params["comparator"])
    bound = params["bound"]
    satisfied = {
        NumericComparator.GE: observed >= bound,
        NumericComparator.LE: observed <= bound,
        NumericComparator.GT: observed > bound,
        NumericComparator.LT: observed < bound,
        NumericComparator.EQ: observed == bound,
    }[comparator]
    return CheckOutcome.SATISFIED if satisfied else CheckOutcome.VIOLATED


def ordered_contains(observed: object, params: dict) -> CheckOutcome:
    expected = params["expected"]
    if not isinstance(observed, list):
        return CheckOutcome.VIOLATED
    # expected must appear as an ordered (not necessarily contiguous)
    # subsequence of observed.
    index = 0
    for item in observed:
        if index < len(expected) and item == expected[index]:
            index += 1
    return CheckOutcome.SATISFIED if index == len(expected) else CheckOutcome.VIOLATED


_DISPATCH: Dict[CheckKind, Callable[[object, dict], CheckOutcome]] = {
    CheckKind.EXACT_EQUALS: exact_equals,
    CheckKind.SUBSET: subset,
    CheckKind.REGEX_MATCH: regex_match,
    CheckKind.NUMERIC_THRESHOLD: numeric_threshold,
    CheckKind.ORDERED_CONTAINS: ordered_contains,
}


def evaluate_value(kind: CheckKind, observed: object, params: dict) -> CheckOutcome:
    """Dispatch to the pure check for a present observed value."""

    try:
        func = _DISPATCH[kind]
    except KeyError:  # unreachable: CheckKind is closed and validated upstream
        raise ValueError(f"unknown check kind: {kind!r}")
    return func(observed, params)
