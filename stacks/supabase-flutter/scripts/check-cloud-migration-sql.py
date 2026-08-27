#!/usr/bin/env python3
"""Reject migration input that can escape the cloud runner's transaction."""

from __future__ import annotations

from pathlib import Path
import re
import sys


MAX_MIGRATION_BYTES = 4 * 1024 * 1024
DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
TRANSACTION_STARTS = {
    "ABORT",
    "BEGIN",
    "COMMIT",
    "END",
    "ROLLBACK",
    "SAVEPOINT",
}


class UnsafeMigration(ValueError):
    pass


def identifier_continuation(char: str) -> bool:
    """Match PostgreSQL's high-bit-inclusive unquoted identifier boundary."""
    return char.isalnum() or char in "_$" or ord(char) >= 128


def normal_sql(text: str) -> str:
    """Blank quoted/comment text while preserving statement separators."""
    if "\x00" in text:
        raise UnsafeMigration("NUL byte")
    output: list[str] = []
    state = "normal"
    dollar = ""
    block_depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        pair = text[index : index + 2]
        if state == "normal":
            if pair == "--":
                output.extend("  ")
                state = "line-comment"
                index += 2
                continue
            if pair == "/*":
                output.extend("  ")
                state = "block-comment"
                block_depth = 1
                index += 2
                continue
            if char == "'":
                output.append(" ")
                escape_prefix = (
                    index > 0
                    and text[index - 1] in "Ee"
                    and (
                        index < 2
                        or not identifier_continuation(text[index - 2])
                    )
                )
                state = "escape-single-quote" if escape_prefix else "single-quote"
                index += 1
                continue
            if char == '"':
                output.append(" ")
                state = "double-quote"
                index += 1
                continue
            if char == "$":
                match = DOLLAR_TAG.match(text, index)
                previous_is_identifier = index > 0 and identifier_continuation(
                    text[index - 1]
                )
                if match and not previous_is_identifier:
                    dollar = match.group(0)
                    output.extend(" " * len(dollar))
                    state = "dollar-quote"
                    index = match.end()
                    continue
            if char == "\\":
                raise UnsafeMigration("psql meta-command")
            output.append(char)
            index += 1
            continue

        if state == "line-comment":
            output.append("\n" if char == "\n" else " ")
            index += 1
            if char == "\n":
                state = "normal"
            continue

        if state == "block-comment":
            if pair == "/*":
                output.extend("  ")
                block_depth += 1
                index += 2
            elif pair == "*/":
                output.extend("  ")
                block_depth -= 1
                index += 2
                if block_depth == 0:
                    state = "normal"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if state == "single-quote":
            if char == "\\":
                raise UnsafeMigration(
                    "backslash in an ordinary string is ambiguous across PostgreSQL string modes"
                )
            if pair == "''":
                output.extend("  ")
                index += 2
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
                if char == "'":
                    state = "normal"
            continue

        if state == "escape-single-quote":
            if char == "\\":
                output.append(" ")
                index += 1
                if index >= len(text):
                    raise UnsafeMigration("unterminated escape-single-quote")
                output.append("\n" if text[index] == "\n" else " ")
                index += 1
            elif pair == "''":
                output.extend("  ")
                index += 2
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
                if char == "'":
                    state = "normal"
            continue

        if state == "double-quote":
            if pair == '""':
                output.extend("  ")
                index += 2
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
                if char == '"':
                    state = "normal"
            continue

        if state == "dollar-quote":
            if text.startswith(dollar, index):
                output.extend(" " * len(dollar))
                index += len(dollar)
                state = "normal"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue

        raise AssertionError(state)

    if state not in {"normal", "line-comment"}:
        raise UnsafeMigration(f"unterminated {state}")
    return "".join(output)


def check_transaction_control(text: str) -> None:
    for statement in normal_sql(text).split(";"):
        words = re.findall(r"[A-Za-z_]+", statement.upper())
        if not words:
            continue
        if words[0] in TRANSACTION_STARTS:
            raise UnsafeMigration(f"top-level {words[0]} transaction control")
        if words[:2] in (["START", "TRANSACTION"], ["PREPARE", "TRANSACTION"]):
            raise UnsafeMigration("top-level transaction control")
        if words[:2] == ["RELEASE", "SAVEPOINT"]:
            raise UnsafeMigration("top-level RELEASE SAVEPOINT")
        if words[:2] == ["SET", "TRANSACTION"] or words[:4] == [
            "SET",
            "SESSION",
            "CHARACTERISTICS",
            "AS",
        ]:
            raise UnsafeMigration("transaction-characteristic override")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check-cloud-migration-sql.py MIGRATION_DIR")
    root = Path(sys.argv[1])
    if not root.is_dir():
        raise SystemExit("migration directory is missing")
    migrations = sorted(root.glob("*.sql"), key=lambda path: path.name)
    for migration in migrations:
        try:
            size = migration.stat().st_size
            if size > MAX_MIGRATION_BYTES:
                raise UnsafeMigration("file exceeds 4 MiB scanner bound")
            check_transaction_control(migration.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, UnsafeMigration) as exc:
            raise SystemExit(f"unsafe cloud migration {migration.name}: {exc}") from None
    print(f"cloud migration SQL guard: OK files={len(migrations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
