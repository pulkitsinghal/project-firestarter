from __future__ import annotations

import unittest

from ..checks import evaluate_value
from ..contracts import CheckKind, CheckOutcome


class CheckFunctionTests(unittest.TestCase):
    def test_exact_equals(self) -> None:
        self.assertEqual(
            evaluate_value(CheckKind.EXACT_EQUALS, "north", {"expected": "north"}),
            CheckOutcome.SATISFIED,
        )
        self.assertEqual(
            evaluate_value(CheckKind.EXACT_EQUALS, ["a", "b"], {"expected": ["a", "b"]}),
            CheckOutcome.SATISFIED,
        )
        self.assertEqual(
            evaluate_value(CheckKind.EXACT_EQUALS, "south", {"expected": "north"}),
            CheckOutcome.VIOLATED,
        )

    def test_subset(self) -> None:
        self.assertEqual(
            evaluate_value(CheckKind.SUBSET, ["a", "b", "c"], {"expected": ["a", "c"]}),
            CheckOutcome.SATISFIED,
        )
        self.assertEqual(
            evaluate_value(CheckKind.SUBSET, ["a"], {"expected": ["a", "c"]}),
            CheckOutcome.VIOLATED,
        )

    def test_regex_match(self) -> None:
        self.assertEqual(
            evaluate_value(CheckKind.REGEX_MATCH, "case-42", {"pattern": "case-[0-9]+"}),
            CheckOutcome.SATISFIED,
        )
        # fullmatch: a trailing suffix is not a match.
        self.assertEqual(
            evaluate_value(
                CheckKind.REGEX_MATCH, "case-42x", {"pattern": "case-[0-9]+"}
            ),
            CheckOutcome.VIOLATED,
        )

    def test_numeric_threshold(self) -> None:
        self.assertEqual(
            evaluate_value(
                CheckKind.NUMERIC_THRESHOLD, 3, {"comparator": "le", "bound": 5}
            ),
            CheckOutcome.SATISFIED,
        )
        self.assertEqual(
            evaluate_value(
                CheckKind.NUMERIC_THRESHOLD, 9, {"comparator": "le", "bound": 5}
            ),
            CheckOutcome.VIOLATED,
        )
        for comparator, value, bound, expected in (
            ("ge", 5, 5, CheckOutcome.SATISFIED),
            ("gt", 5, 5, CheckOutcome.VIOLATED),
            ("lt", 4, 5, CheckOutcome.SATISFIED),
            ("eq", 5, 5, CheckOutcome.SATISFIED),
        ):
            self.assertEqual(
                evaluate_value(
                    CheckKind.NUMERIC_THRESHOLD,
                    value,
                    {"comparator": comparator, "bound": bound},
                ),
                expected,
            )

    def test_ordered_contains(self) -> None:
        self.assertEqual(
            evaluate_value(
                CheckKind.ORDERED_CONTAINS,
                ["intro", "body", "cite", "close"],
                {"expected": ["intro", "cite"]},
            ),
            CheckOutcome.SATISFIED,
        )
        # order matters: reversed expectation is not a subsequence.
        self.assertEqual(
            evaluate_value(
                CheckKind.ORDERED_CONTAINS,
                ["intro", "body", "cite"],
                {"expected": ["cite", "intro"]},
            ),
            CheckOutcome.VIOLATED,
        )

    def test_type_mismatch_violates(self) -> None:
        # A present value of the wrong shape is a genuine violation, not a crash
        # and not unavailable.
        self.assertEqual(
            evaluate_value(CheckKind.SUBSET, "north", {"expected": ["a"]}),
            CheckOutcome.VIOLATED,
        )
        self.assertEqual(
            evaluate_value(
                CheckKind.NUMERIC_THRESHOLD, "5", {"comparator": "le", "bound": 5}
            ),
            CheckOutcome.VIOLATED,
        )
        self.assertEqual(
            evaluate_value(
                CheckKind.NUMERIC_THRESHOLD, True, {"comparator": "ge", "bound": 0}
            ),
            CheckOutcome.VIOLATED,
        )
        self.assertEqual(
            evaluate_value(CheckKind.REGEX_MATCH, 42, {"pattern": "[0-9]+"}),
            CheckOutcome.VIOLATED,
        )


if __name__ == "__main__":
    unittest.main()
