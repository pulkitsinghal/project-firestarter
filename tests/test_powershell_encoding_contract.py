"""Offline contract: every PowerShell script parses on Windows PowerShell 5.1.

Windows PowerShell 5.1 reads a .ps1 file that has no byte-order mark using the
system ANSI code page. UTF-8 punctuation such as em dashes, box-drawing rules
or arrows then turns into mojibake, and some of those bytes decode to smart
quotes that PowerShell treats as string delimiters, so the script fails to
parse before it runs. PowerShell 7 and the Linux CI runners never see this.
Keep every script ASCII-only, or save it with a UTF-8 BOM when it truly needs
non-ASCII text.
"""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UTF8_BOM = b"\xef\xbb\xbf"
PATTERNS = ("*.ps1", "*.psm1", "*.psd1")
SKIPPED_DIRS = {".git", "node_modules"}


def powershell_scripts() -> list[Path]:
    return sorted(
        path
        for pattern in PATTERNS
        for path in ROOT.rglob(pattern)
        if not SKIPPED_DIRS.intersection(path.relative_to(ROOT).parts)
    )


class PowerShellEncodingContract(unittest.TestCase):
    def test_repository_ships_powershell_scripts(self) -> None:
        self.assertTrue(powershell_scripts(), "expected PowerShell scripts to check")

    def test_every_script_is_ascii_or_has_a_utf8_bom(self) -> None:
        offenders = []
        for path in powershell_scripts():
            data = path.read_bytes()
            if data.startswith(UTF8_BOM):
                continue
            if any(byte > 0x7F for byte in data):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(
            offenders,
            [],
            "these scripts contain non-ASCII bytes without a UTF-8 BOM and will "
            "not parse on Windows PowerShell 5.1; use ASCII or save with a BOM",
        )


if __name__ == "__main__":
    unittest.main()
