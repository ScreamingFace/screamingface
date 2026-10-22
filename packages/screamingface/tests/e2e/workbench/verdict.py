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

from workbench.bundle import (
    EVENTS_FILE,
    SpansFor,
    prepare_bundle,
    settled,
    write_bundle,
    write_telemetry,
)
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
    *,
    spans_for: SpansFor | None = None,
) -> None:
    """Run ``path`` on ``target``, write its bundle under ``out``; fail (pytest) with reasons.

    Telemetry (spec §3.6): the notebook records its SDK events into ``<bundle>/events.jsonl``
    (``EVENTS_PATH``) as it runs; at bundle time the spans of its trace ids are copied in from
    ``spans_for`` (the session's ``OtlpReceiver.spans_for``). Telemetry never decides the
    verdict: missing spans are explained in ``telemetry.json``, not failed, and an ``OSError``
    writing them (disk full, permission) is a redacted note in the bundle — it never skips
    ``write_bundle``, so the verdict evidence always lands.
    """
    meta = _meta(path)
    if target.name not in meta.get("targets", []):
        pytest.skip(f"{path.stem} does not declare target {target.name}")
    bundle_dir = prepare_bundle(out, target.name, path.stem)
    params = {
        "ENGINE_URL": target.engine_url,
        "SCOREBOARD_URL": target.scoreboard_url,
        "EVENTS_PATH": str(bundle_dir / EVENTS_FILE),
    }
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

    # The services batch their spans: wait (bounded) for the run's last batch to land.
    notes: list[str] = []
    try:
        write_telemetry(bundle_dir, trace_ids, settled(spans_for) if spans_for else None)
    except OSError as exc:
        notes.append(redact(f"telemetry not written: {type(exc).__name__}: {exc}"))
    bundle = write_bundle(
        out,
        target=target.name,
        notebook=path.stem,
        run=run,
        chain=chain,
        passed=not reasons,
        reasons=reasons,
        notes=notes,
    )
    record_property("bundle", redact(str(bundle)))
    if reasons:
        pytest.fail(redact(f"{'; '.join(reasons)} — evidence: {bundle}"), pytrace=False)
