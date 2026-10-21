"""One workbench notebook's verdict (e2e workbench spec §2 D3): the notebook AND the trace chain.

A module, not the test body, so the redaction contract (review finding 1) is exercised end to
end by a pytester lane (``test_failure_output_redaction.py``) without a live target.

INVARIANT: no string derived from the run leaves this function unredacted. Reasons are
redacted once, before ANY sink (bundle, JUnit properties, the failure message), and the
failure is raised with ``pytrace=False`` so no traceback frame (``-l`` / ``--showlocals``)
re-prints ``run.error`` raw. The lane's report hook (``conftest.py``) is the second net for
everything else a report carries.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import nbformat
import pytest

from workbench.bundle import write_bundle
from workbench.evidence import collect
from workbench.redaction import redact
from workbench.result_check import check_result
from workbench.runner import notebook_deadline_s, run_notebook
from workbench.targets import LiveTarget

_ANSI = re.compile(r"\x1b\[[0-9;]*m")  # nbclient tracebacks carry colour codes


def _meta(path: Path) -> dict[str, Any]:
    return dict(nbformat.read(path, as_version=4).metadata.get("workbench", {}))


def judge_notebook(
    path: Path,
    target: LiveTarget,
    out: Path,
    record_property: Callable[[str, object], None],
) -> None:
    """Run ``path`` on ``target``, write its bundle under ``out``; fail (pytest) with reasons."""
    meta = _meta(path)
    if target.name not in meta.get("targets", []):
        pytest.skip(f"{path.stem} does not declare target {target.name}")
    params = {"ENGINE_URL": target.engine_url, "SCOREBOARD_URL": target.scoreboard_url}
    run = run_notebook(path, params | target.params, deadline_s=notebook_deadline_s())

    trace_ids, result_reasons = check_result(run.result, meta.get("required_result", []))
    # Spec §3.3: the junit entry carries the trace id(s), so CI links a test row to its trace.
    # The ids are TRACE_ID-validated hex; redacted anyway so no property bypasses the redactor.
    record_property("trace_ids", redact(",".join(trace_ids)))
    chain = collect(trace_ids, target.sources)
    raw: list[str] = []
    if run.error:
        last = (_ANSI.sub("", run.error).strip().splitlines() or ["?"])[-1]
        raw.append(f"notebook failed: {last}")
    raw += result_reasons
    raw += chain.reasons(target.required_hops)
    reasons = [redact(r) for r in raw]

    bundle = write_bundle(
        out,
        target=target.name,
        notebook=path.stem,
        run=run,
        chain=chain,
        passed=not reasons,
        reasons=reasons,
    )
    record_property("bundle", redact(str(bundle)))
    if reasons:
        pytest.fail(redact(f"{'; '.join(reasons)} — evidence: {bundle}"), pytrace=False)
