"""DEC-1: the parity gate checker (uniform executor PRD 05 DC-H1, DC-E1)."""

import importlib.util
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "parity_gate_check.py"


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("parity_gate_check", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(*, item_results: list[str], rows: list[str]) -> str:
    sections = []
    for number, result in enumerate(item_results, start=1):
        body = f"## {number}. item\n\nResult: {result}\n"
        if number == 2:
            body += "\n| file | test | behavior | direct path |\n|---|---|---|---|\n"
            body += "\n".join(rows) + "\n"
        sections.append(body)
    return "# Gate\n\n" + "\n".join(sections)


_GOOD_ROWS = [
    "| a.py | test_x | 403 | test_missing_identity_403_nothing_queued |",
    "| a.py | test_y | cap 2 per worker | N/A: replaced by the queue's per-caller cap |",
]


def test_parity_gate_record_complete() -> None:
    """DEC-1: five passing items and a mapping table with no blank rows → the gate passes."""
    assert _checker().check(_record(item_results=["PASS"] * 5, rows=_GOOD_ROWS)) == []


def test_a_failing_or_missing_item_is_named() -> None:
    """DC-E1: the checker names the failing item, and a missing one."""
    problems = _checker().check(
        _record(item_results=["PASS", "PASS", "FAIL", "PASS"], rows=_GOOD_ROWS)
    )
    assert "item 3: Result is FAIL" in problems
    assert "item 5: section `## 5.` is missing" in problems


def test_a_blank_mapping_row_or_reasonless_na_fails() -> None:
    rows = [
        "| a.py | test_x | 403 | |",
        "| a.py | test_y | cap | N/A: |",
        "| a.py | test_z | x | NONE |",
    ]
    problems = _checker().check(_record(item_results=["PASS"] * 5, rows=rows))
    assert "item 2: a.py::test_x has no direct-path test" in problems
    assert "item 2: a.py::test_y is N/A with no reason" in problems
    assert "item 2: a.py::test_z has no direct-path test" in problems
