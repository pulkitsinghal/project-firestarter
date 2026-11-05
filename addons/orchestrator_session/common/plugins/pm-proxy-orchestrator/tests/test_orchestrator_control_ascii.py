"""Regression tests (#194) for ASCII-only digit discipline and fail-closed
timestamp parsing in the orchestrator control CLI.

A `\\d` in a Python ``str`` regex matches any Unicode decimal digit (for
example Arabic-Indic ``U+0661``), so a non-ASCII timestamp or cache-buster
version could slip past a ``\\d``-based gate and reach
``datetime.fromisoformat``, which raised an *unbounded* ``ValueError`` -
escaping the schema-validation contract that otherwise fails closed with a
bounded ``ControlError``. The control CLI now uses ASCII ``[0-9]`` in
``TIME_RE`` and the dispatcher-adoption version gate, and wraps ``utc_instant``
so any malformed value fails closed.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[4]
CLI = (
    REPO_ROOT
    / "addons"
    / "orchestrator_session"
    / "common"
    / "orchestrator-control"
    / "orchestrator_control.py"
)
SPEC = importlib.util.spec_from_file_location("orchestrator_control", CLI)
assert SPEC is not None and SPEC.loader is not None
OC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OC)

ACP_PATH = CLI.with_name("adaptive_capacity_policy.py")
ACP_SPEC = importlib.util.spec_from_file_location("adaptive_capacity_policy", ACP_PATH)
assert ACP_SPEC is not None and ACP_SPEC.loader is not None
ACP = importlib.util.module_from_spec(ACP_SPEC)
# Register before exec_module so the module's @dataclass definitions can resolve
# their own module via sys.modules[cls.__module__] during class processing.
sys.modules[ACP_SPEC.name] = ACP
ACP_SPEC.loader.exec_module(ACP)


def _to_arabic_indic(ascii_text: str) -> str:
    """Rewrite ASCII digits as Arabic-Indic ones, leaving separators ASCII."""
    return ascii_text.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


ASCII_TS = "2026-01-01T00:00:00Z"
ARABIC_TS = _to_arabic_indic(ASCII_TS)


class TimeReAsciiTest(unittest.TestCase):
    def test_ascii_rfc3339_matches(self) -> None:
        self.assertIsNotNone(OC.TIME_RE.fullmatch(ASCII_TS))

    def test_fractional_ascii_matches(self) -> None:
        self.assertIsNotNone(OC.TIME_RE.fullmatch("2026-01-01T00:00:00.123Z"))

    def test_arabic_indic_digits_rejected(self) -> None:
        # The gate must not admit non-ASCII decimal digits.
        self.assertIsNone(OC.TIME_RE.fullmatch(ARABIC_TS))


class TimestampGateTest(unittest.TestCase):
    def test_ascii_timestamp_accepted(self) -> None:
        self.assertEqual(OC.timestamp(ASCII_TS), ASCII_TS)

    def test_arabic_indic_timestamp_fails_closed(self) -> None:
        with self.assertRaises(OC.ControlError) as caught:
            OC.timestamp(ARABIC_TS)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")


class UtcInstantFailClosedTest(unittest.TestCase):
    def test_ascii_instant_parses(self) -> None:
        parsed = OC.utc_instant(ASCII_TS)
        self.assertEqual(parsed, dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))

    def test_non_ascii_instant_raises_bounded_control_error(self) -> None:
        # Core #194 guard: a value that slipped past (or around) TIME_RE must
        # fail closed with a bounded ControlError, never a raw ValueError.
        with self.assertRaises(OC.ControlError) as caught:
            OC.utc_instant(ARABIC_TS)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_malformed_instant_raises_bounded_control_error(self) -> None:
        with self.assertRaises(OC.ControlError) as caught:
            OC.utc_instant("not-a-timestamp")
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")


def _adoption_request(plugin_version: str) -> dict:
    """A minimal valid covered-path adoption request varying only the version."""
    return {
        "interface_version": OC.INTERFACE_VERSION,
        "request_id": "req-0-4-12-adoption-canary",
        "adoption_mode": "COVERED_PATH_GUARDRAIL",
        "plugin_version": plugin_version,
        "proofs": {
            "pre_tool_denial_verified": True,
            "typed_mcp_control_verified": True,
            "reserved_create_admission_verified": True,
            "lifecycle_debt_clear_verified": True,
            "archive_refill_fence_verified": True,
            "no_side_effect_canary_verified": True,
            "hosted_paths_uncovered": True,
            "universal_coverage_claimed": False,
        },
        "now": ASCII_TS,
    }


class DispatcherAdoptionVersionAsciiTest(unittest.TestCase):
    def test_ascii_cachebuster_version_accepted(self) -> None:
        version = "0.4.12+codex.20261104193138"
        result = OC.validate_dispatcher_adoption(_adoption_request(version))
        self.assertEqual(result["plugin_version"], version)

    def test_plain_base_version_accepted(self) -> None:
        result = OC.validate_dispatcher_adoption(_adoption_request("0.4.12"))
        self.assertEqual(result["plugin_version"], "0.4.12")

    def test_arabic_indic_cachebuster_rejected(self) -> None:
        version = "0.4.12+codex." + _to_arabic_indic("20261104193138")
        with self.assertRaises(OC.ControlError) as caught:
            OC.validate_dispatcher_adoption(_adoption_request(version))
        self.assertEqual(caught.exception.code, "DISPATCHER_ADOPTION_INVALID")


class AdaptiveCapacityPolicyTimestampAsciiTest(unittest.TestCase):
    """The sibling audit-mode policy in the same control dir shares the gate."""

    def test_ascii_timestamp_accepted(self) -> None:
        value, parsed = ACP._timestamp(ASCII_TS, "now")
        self.assertEqual(value, ASCII_TS)
        self.assertEqual(parsed, dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))

    def test_arabic_indic_timestamp_rejected(self) -> None:
        self.assertIsNone(ACP.RFC3339_UTC.fullmatch(ARABIC_TS))
        with self.assertRaises(ACP.AuditInputError):
            ACP._timestamp(ARABIC_TS, "now")


if __name__ == "__main__":
    unittest.main()
