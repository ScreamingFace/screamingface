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

    ids = ", ".join(chain.trace_ids) or "—"
    why = "; ".join(reasons) or "—"
    _append_row(root, target, notebook, "PASS" if passed else "FAIL", ids, why)
    return out


SETUP_ERROR_FILE = "setup_error.txt"
SETUP_ROW = "(target setup)"


def write_setup_failure(root: Path, *, target: str, skipped: bool, detail: str) -> Path:
    """Record a target that never came up: ``root/setup_error.txt`` plus a summary row.

    WHY (review finding 4): no notebook ran, so no bundle exists; without this the evidence dir
    is empty and the reviewer has no artifact saying why. ``detail`` is redacted here.
    """
    root.mkdir(parents=True, exist_ok=True)
    clean = redact(detail).rstrip()
    path = root / SETUP_ERROR_FILE
    with path.open("a") as fh:
        fh.write(f"target: {target}\n{clean}\n")
    last = (clean.splitlines() or ["?"])[-1]
    _append_row(root, target, SETUP_ROW, "SETUP-SKIP" if skipped else "SETUP-ERROR", "—", last)
    return path


def _append_row(root: Path, target: str, notebook: str, outcome: str, ids: str, why: str) -> None:
    summary = root / "summary.md"
    if not summary.exists():
        summary.write_text(_HEADER)
    row = f"| {_cell(target)} | {_cell(notebook)} | {outcome} | {ids} | {_cell(why)} |\n"
    with summary.open("a") as fh:
        fh.write(redact(row))
