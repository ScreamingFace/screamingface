"""Each workbench notebook × the selected target. Passes only if the notebook AND the trace
chain agree (e2e workbench spec §2 D3)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import nbformat
import pytest

from workbench.build_notebooks import NOTEBOOK_DIR
from workbench.bundle import write_bundle
from workbench.evidence import collect
from workbench.result_check import check_result
from workbench.runner import run_notebook
from workbench.targets import LiveTarget, selected_target

NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
_ANSI = re.compile(r"\x1b\[[0-9;]*m")  # nbclient tracebacks carry colour codes
# Resolved at collection so the id reads test_notebook[<target>-<stem>]; an unknown target
# name fails collection loudly rather than running against a guess.
_TARGET = selected_target()


def _meta(path: Path) -> dict[str, Any]:
    return dict(nbformat.read(path, as_version=4).metadata.get("workbench", {}))


@pytest.mark.e2e
@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: f"{_TARGET}-{p.stem}")
def test_notebook(
    path: Path,
    live_target: LiveTarget,
    workbench_out: Path,
    record_property: Callable[[str, object], None],
) -> None:
    meta = _meta(path)
    if live_target.name not in meta.get("targets", []):
        pytest.skip(f"{path.stem} does not declare target {live_target.name}")
    params = {"ENGINE_URL": live_target.engine_url, "SCOREBOARD_URL": live_target.scoreboard_url}
    run = run_notebook(path, params | live_target.params)

    trace_ids, result_reasons = check_result(run.result, meta.get("required_result", []))
    # Spec §3.3: the junit entry carries the trace id(s), so CI links a test row to its trace.
    record_property("trace_ids", ",".join(trace_ids))
    chain = collect(trace_ids, live_target.sources)
    reasons: list[str] = []
    if run.error:
        last = (_ANSI.sub("", run.error).strip().splitlines() or ["?"])[-1]
        reasons.append(f"notebook failed: {last}")
    reasons += result_reasons
    if trace_ids and (missing := chain.missing(live_target.required_hops)):
        reasons.append(f"trace {trace_ids} not found in: {', '.join(missing)}")
    if chain.unattributed:
        reasons.append(f"{len(chain.unattributed)} aigateway lines lack gateway_call_id")

    bundle = write_bundle(
        workbench_out,
        target=live_target.name,
        notebook=path.stem,
        run=run,
        chain=chain,
        passed=not reasons,
        reasons=reasons,
    )
    record_property("bundle", str(bundle))
    assert not reasons, f"{'; '.join(reasons)} — evidence: {bundle}"
