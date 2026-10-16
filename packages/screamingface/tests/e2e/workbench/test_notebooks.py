"""Each workbench notebook × the selected target. Passes only if the notebook AND the trace
chain agree (e2e workbench spec §2 D3)."""

from __future__ import annotations

import re
from pathlib import Path

import nbformat
import pytest

from workbench.build_notebooks import NOTEBOOK_DIR
from workbench.bundle import write_bundle
from workbench.evidence import collect
from workbench.runner import run_notebook
from workbench.targets import LiveTarget, selected_target

NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
_ANSI = re.compile(r"\x1b\[[0-9;]*m")  # nbclient tracebacks carry colour codes
# Resolved at collection so the id reads test_notebook[<target>-<stem>]; an unknown target
# name fails collection loudly rather than running against a guess.
_TARGET = selected_target()


def _supports(path: Path, target: str) -> bool:
    meta = nbformat.read(path, as_version=4).metadata.get("workbench", {})
    return target in meta.get("targets", [])


@pytest.mark.e2e
@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: f"{_TARGET}-{p.stem}")
def test_notebook(path: Path, live_target: LiveTarget, workbench_out: Path) -> None:
    if not _supports(path, live_target.name):
        pytest.skip(f"{path.stem} does not declare target {live_target.name}")
    params = {"ENGINE_URL": live_target.engine_url, "SCOREBOARD_URL": live_target.scoreboard_url}
    run = run_notebook(path, params | live_target.params)

    trace_ids = [str(t) for t in (run.result or {}).get("trace_ids", [])]
    chain = collect(trace_ids, live_target.sources)
    reasons: list[str] = []
    if run.error:
        last = (_ANSI.sub("", run.error).strip().splitlines() or ["?"])[-1]
        reasons.append(f"notebook failed: {last}")
    if not trace_ids:
        reasons.append("no trace id reported by the notebook")
    elif missing := chain.missing(live_target.required_hops):
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
    assert not reasons, f"{'; '.join(reasons)} — evidence: {bundle}"
