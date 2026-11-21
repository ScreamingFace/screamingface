"""The notebook check fails when the executable detach story goes or a paid flag is left on."""

from __future__ import annotations

import copy
import runpy
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).parent.parent / "scripts"


@pytest.fixture(scope="module")
def check() -> Iterator[Callable[[dict[str, Any]], None]]:
    sys.path.insert(0, str(_SCRIPTS))
    try:
        yield runpy.run_path(str(_SCRIPTS / "check_notebooks.py"))["_check_public_story"]
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.fixture
def notebooks() -> dict[str, Any]:
    return copy.deepcopy(runpy.run_path(str(_SCRIPTS / "build_notebooks.py"))["notebooks"]())


def test_the_generated_notebooks_pass(
    check: Callable[[dict[str, Any]], None], notebooks: dict[str, Any]
) -> None:
    check(notebooks)


def test_the_check_fails_without_the_detach_section(
    check: Callable[[dict[str, Any]], None], notebooks: dict[str, Any]
) -> None:
    runs = notebooks["21_runs.ipynb"]
    runs.cells = [
        cell
        for cell in runs.cells
        if "RUN_DETACHED" not in cell.source and "REATTACH_RUN_ID" not in cell.source
    ]

    with pytest.raises(SystemExit, match="RUN_DETACHED = False"):
        check(notebooks)


def _switch_on(notebooks: dict[str, Any], off: str, on: str) -> None:
    for notebook in notebooks.values():
        for cell in notebook.cells:
            if cell.cell_type == "code" and off in cell.source:
                cell.source = cell.source.replace(off, on, 1)
                return
    raise AssertionError(f"no code cell has {off!r}")


@pytest.mark.parametrize(
    "on",
    [
        "RUN_DETACHED = True",
        "RUN_DETACHED=True",
        "RUN_DETACHED = True  # opt in",
        "RUN_DETACHED: bool = True",
    ],
)
def test_the_check_fails_when_the_detached_run_is_on_by_default(
    check: Callable[[dict[str, Any]], None], notebooks: dict[str, Any], on: str
) -> None:
    _switch_on(notebooks, "RUN_DETACHED = False", on)

    with pytest.raises(SystemExit, match="paid"):
        check(notebooks)


@pytest.mark.parametrize(
    ("off", "on"),
    [
        ("RUN_EVALUATION = False", "RUN_EVALUATION=True"),
        ("REPLAY_RESULT = False", "REPLAY_RESULT = True"),
    ],
)
def test_the_check_fails_when_any_paid_flag_is_on_by_default(
    check: Callable[[dict[str, Any]], None], notebooks: dict[str, Any], off: str, on: str
) -> None:
    _switch_on(notebooks, off, on)

    with pytest.raises(SystemExit, match="paid"):
        check(notebooks)
