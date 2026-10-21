"""Write one notebook run's evidence bundle (e2e workbench spec §3.3). Secrets never land.

Redaction is ``workbench.redaction`` (values, never serialised JSON — see its INVARIANT).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import nbformat

from workbench.evidence import TraceChain
from workbench.redaction import redact, redact_tree
from workbench.runner import NotebookRun

_HEADER = "| target | notebook | outcome | trace ids | reasons |\n|---|---|---|---|---|\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def write_bundle(
    root: Path,
    *,
    target: str,
    notebook: str,
    run: NotebookRun,
    chain: TraceChain,
    passed: bool,
    reasons: Sequence[str],
) -> Path:
    """Write ``root/<target>/<notebook>/`` and append one row to ``root/summary.md``."""
    out = root / target / notebook
    (out / "logs").mkdir(parents=True, exist_ok=True)

    executed = nbformat.from_dict(redact_tree(run.executed))
    nbformat.write(executed, out / "executed.ipynb")

    for hop in chain.hops:
        (out / "logs" / f"{hop.name}.txt").write_text(redact("\n".join(hop.lines)))

    trace = chain.to_json() | {
        "passed": passed,
        "reasons": list(reasons),
        "result": run.result,
        "error": run.error,
    }
    (out / "trace.json").write_text(json.dumps(redact_tree(trace), indent=2))

    summary = root / "summary.md"
    if not summary.exists():
        summary.write_text(_HEADER)
    ids = ", ".join(chain.trace_ids) or "—"
    why = "; ".join(reasons) or "—"
    outcome = "PASS" if passed else "FAIL"
    row = f"| {_cell(target)} | {_cell(notebook)} | {outcome} | {ids} | {_cell(why)} |\n"
    with summary.open("a") as fh:
        fh.write(redact(row))
    return out
