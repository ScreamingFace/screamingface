"""Each workbench notebook × the selected target. Passes only if the notebook AND the trace
chain agree (e2e workbench spec §2 D3) — the verdict itself is ``workbench.verdict``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from workbench.build_notebooks import NOTEBOOK_DIR
from workbench.targets import LiveTarget, selected_target
from workbench.verdict import judge_notebook

NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
# Resolved at collection so the id reads test_notebook[<target>-<stem>]; an unknown target
# name fails collection loudly rather than running against a guess.
_TARGET = selected_target()


@pytest.mark.e2e
@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: f"{_TARGET}-{p.stem}")
def test_notebook(
    path: Path,
    live_target: LiveTarget,
    workbench_out: Path,
    record_property: Callable[[str, object], None],
) -> None:
    judge_notebook(path, live_target, workbench_out, record_property)
