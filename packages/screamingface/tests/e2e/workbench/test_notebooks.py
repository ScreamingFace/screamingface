"""Each workbench notebook × the selected target. Passes only if the notebook AND the trace
chain agree (e2e workbench spec §2 D3) — the verdict itself is ``workbench.verdict``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from workbench.build_notebooks import notebooks_for
from workbench.otlp_receiver import OtlpReceiver
from workbench.targets import LiveTarget, selected_target
from workbench.verdict import judge_notebook

# Resolved at collection so the id reads test_notebook[<target>-<stem>]; an unknown target
# name fails collection loudly rather than running against a guess. Only notebooks that DECLARE
# the target are collected: an undeclared one never becomes a skip REQUIRE_ALL would fail.
_TARGET = selected_target()
NOTEBOOKS = notebooks_for(_TARGET)


@pytest.mark.e2e
@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: f"{_TARGET}-{p.stem}")
def test_notebook(
    path: Path,
    live_target: LiveTarget,
    workbench_out: Path,
    otlp_receiver: OtlpReceiver,
    record_property: Callable[[str, object], None],
) -> None:
    judge_notebook(
        path, live_target, workbench_out, record_property, spans_for=otlp_receiver.spans_for
    )
