"""The inspect-extra suites live in exactly one place CI knows about.

INVARIANT: every test file that `importorskip`s the inspect packages sits under
`tests/unit/inspect/`, because that directory is the ONLY path the workflow's
extra-installed lane runs. An importorskip file anywhere else is collected only by
the extra-less lane, skips there by construction, and is therefore green-by-skip
in every CI lane forever — the exact rot that left the importer's regression pins
running nowhere (review finding on PR #1009, when the extra lane was a hand-kept
file list).
"""

from __future__ import annotations

import re
from pathlib import Path

# Matches a real importorskip call for the inspect packages. This file scans
# itself too, so nothing in it — pattern source, docstrings, messages — may spell
# out a literal importorskip("inspect_… call (the backslashes in the pattern's
# own source keep IT safe; prose must simply not quote the call).
_INSPECT_IMPORTORSKIP: re.Pattern[str] = re.compile(
    r"importorskip\(\s*[\"'](?:inspect_ai|inspect_evals)"
)

_TESTS_ROOT: Path = Path(__file__).resolve().parent.parent
_INSPECT_SUITE_DIR: Path = _TESTS_ROOT / "unit" / "inspect"


def test_inspect_dependent_suites_live_in_the_inspect_dir() -> None:
    """A test needing the inspect extra outside tests/unit/inspect/ runs in no CI lane."""

    strays: list[str] = sorted(
        str(path.relative_to(_TESTS_ROOT))
        for path in _TESTS_ROOT.rglob("test_*.py")
        if _INSPECT_SUITE_DIR not in path.parents
        and _INSPECT_IMPORTORSKIP.search(path.read_text(encoding="utf-8"))
    )
    assert strays == [], (
        f"tests that importorskip the inspect packages sit outside tests/unit/inspect/: "
        f"{strays} — move the file there, or CI's extra lane will never run it"
    )


def test_the_inspect_suite_dir_is_not_empty() -> None:
    """Guards the lane's target: an emptied/renamed dir would make CI's extra lane a no-op."""

    files: list[Path] = list(_INSPECT_SUITE_DIR.glob("test_*.py"))
    assert files, (
        f"{_INSPECT_SUITE_DIR} holds no test files — the CI extra lane points at it "
        "and would silently run nothing"
    )
