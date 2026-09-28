"""DEC-1: check the node-tier parity gate record before the removal (uniform executor PRD 05).

    uv run python scripts/parity_gate_check.py [<gate record>]

(default record: docs/plans/uniform-executor/measurements/parity-gate.md)

The record must hold the five DC-H1 items as sections `## 1.` … `## 5.`, each with a line
`Result: PASS` (or `Result: FAIL`), and a mapping table whose rows each name a direct-path test
or say `N/A: <reason>`. Exit status 0 only when every item passes and no mapping row is blank —
the removal does not start otherwise (DC-E1), and the output names each failing item.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_RECORD = (
    Path(__file__).resolve().parents[1] / "docs/plans/uniform-executor/measurements/parity-gate.md"
)
ITEMS = 5
_SECTION = re.compile(r"^## (\d+)\.", re.MULTILINE)
_RESULT = re.compile(r"^Result:\s*(PASS|FAIL)\b", re.MULTILINE)


def check(text: str) -> list[str]:
    """Every problem with the gate record; empty when the gate passes."""
    problems: list[str] = []
    sections = _sections(text)
    for number in range(1, ITEMS + 1):
        body = sections.get(number)
        if body is None:
            problems.append(f"item {number}: section `## {number}.` is missing")
            continue
        result = _RESULT.search(body)
        if result is None:
            problems.append(f"item {number}: no `Result: PASS|FAIL` line")
        elif result.group(1) != "PASS":
            problems.append(f"item {number}: Result is FAIL")
    problems.extend(_mapping_problems(sections.get(2, "")))
    return problems


def _sections(text: str) -> dict[int, str]:
    marks = list(_SECTION.finditer(text))
    out: dict[int, str] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        out[int(mark.group(1))] = text[mark.end() : end]
    return out


def _mapping_problems(item_two: str) -> list[str]:
    """Item 2's table: `| file | test | behavior | direct-path test or N/A: reason |`."""
    rows = [
        line
        for line in item_two.splitlines()
        if line.startswith("|") and not set(line.replace("|", "").strip()) <= {"-", ":", " "}
    ]
    if len(rows) < 2:
        return ["item 2: the mapping table is missing or empty"]
    problems: list[str] = []
    for line in rows[1:]:  # rows[0] is the header
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            problems.append(f"item 2: malformed row {line!r}")
            continue
        mapped = cells[3]
        if not mapped or mapped.upper() in {"NONE", "TODO", "?"}:
            problems.append(f"item 2: {cells[0]}::{cells[1]} has no direct-path test")
        elif mapped.upper().startswith("N/A") and not mapped.partition(":")[2].strip():
            problems.append(f"item 2: {cells[0]}::{cells[1]} is N/A with no reason")
    return problems


def main(argv: list[str]) -> int:
    record = Path(argv[1]) if len(argv) > 1 else DEFAULT_RECORD
    if not record.exists():
        print(f"parity gate record not found: {record}")
        return 2
    problems = check(record.read_text())
    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print(f"PASS {record}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
