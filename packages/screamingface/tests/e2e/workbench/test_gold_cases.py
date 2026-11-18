"""The image input matrix's gold Cases (spec §3.4) are few, answered, and runnable on a Mac.

WHY these checks: the Benchmark path runs every vision model over each gold Case, so the list
sets the path's spend (at most 4 Cases, spec §3.6) and its meaning: a Case with no gold answer
cannot show that the picture arrived. A Benchmark whose Case Digest is sealed on Linux has no
Cases on a Mac's local stack, so a gold Case from one would fail there for the wrong reason.

The Linux-sealed set is read from the picture notebook (``examples/18_picture_benchmarks.ipynb``,
``SEALED_ON_LINUX``), the one place it is maintained, so a newly sealed Benchmark is refused here
without a second list to update.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Final

FIXTURES: Final = Path(__file__).parent / "fixtures" / "image_input"
PICTURE_NOTEBOOK: Final = (
    Path(__file__).resolve().parents[3] / "examples" / "18_picture_benchmarks.ipynb"
)


def _gold_cases() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "gold_cases.json").read_text(encoding="utf-8"))


def _sealed_on_linux() -> set[str]:
    """The picture notebook's ``SEALED_ON_LINUX`` set literal, parsed, never executed."""
    cells: list[dict[str, Any]] = json.loads(PICTURE_NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        for node in ast.parse("".join(cell["source"])).body:
            if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == [
                "SEALED_ON_LINUX"
            ]:
                return set(ast.literal_eval(node.value))
    raise AssertionError(f"no SEALED_ON_LINUX assignment in {PICTURE_NOTEBOOK}")


def test_the_sealed_set_is_found_in_the_picture_notebook() -> None:
    # Guards the parser: an empty set would let every Benchmark through.
    assert "inspect-mmmu_multiple_choice" in _sealed_on_linux()


def test_there_are_two_to_four_gold_cases() -> None:
    assert 2 <= len(_gold_cases()) <= 4


def test_each_gold_case_names_its_benchmark_case_and_answer() -> None:
    for entry in _gold_cases():
        assert set(entry) == {"benchmark", "case", "expected", "note"}, entry
        assert isinstance(entry["benchmark"], str) and entry["benchmark"].strip(), entry
        assert isinstance(entry["case"], int) and entry["case"] >= 1, entry
        assert isinstance(entry["expected"], str) and entry["expected"].strip(), entry
        assert isinstance(entry["note"], str) and entry["note"].strip(), entry


def test_gold_cases_are_unique() -> None:
    keys = [(entry["benchmark"], entry["case"]) for entry in _gold_cases()]
    assert len(keys) == len(set(keys))


def test_no_gold_case_comes_from_a_linux_sealed_benchmark() -> None:
    sealed = _sealed_on_linux()
    assert not [entry for entry in _gold_cases() if entry["benchmark"] in sealed]
