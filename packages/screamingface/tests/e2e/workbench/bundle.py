"""Write one notebook run's evidence bundle (e2e workbench spec §3.3). Secrets never land.

INVARIANT: redaction runs on values, never on serialised JSON. ``bearer\\s+\\S+`` applied to a
JSON document would swallow the closing quote of the string it sits in and corrupt the file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import nbformat

from workbench.evidence import TraceChain
from workbench.runner import NotebookRun

_SECRETS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"(?i)bearer\s+\S+"),
)
_MASK = "[REDACTED]"
_HEADER = "| target | notebook | outcome | trace ids | reasons |\n|---|---|---|---|---|\n"


def redact(text: str) -> str:
    for pattern in _SECRETS:
        text = pattern.sub(_MASK, text)
    return text


def _redact_tree(value: Any) -> Any:
    """Redact every string in a JSON-like tree (dicts, lists, NotebookNodes), keys included."""
    match value:
        case str():
            out: Any = redact(value)
        case dict():
            items: dict[Any, Any] = value  # pyright: ignore[reportUnknownVariableType]
            out = {_redact_tree(k): _redact_tree(v) for k, v in items.items()}
        case list() | tuple():
            seq: Sequence[Any] = value  # pyright: ignore[reportUnknownVariableType]
            out = [_redact_tree(v) for v in seq]
        case _:
            out = value
    return out


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

    executed = nbformat.from_dict(_redact_tree(run.executed))
    nbformat.write(executed, out / "executed.ipynb")

    for hop in chain.hops:
        (out / "logs" / f"{hop.name}.txt").write_text(redact("\n".join(hop.lines)))

    trace = chain.to_json() | {
        "passed": passed,
        "reasons": list(reasons),
        "result": run.result,
        "error": run.error,
    }
    (out / "trace.json").write_text(json.dumps(_redact_tree(trace), indent=2))

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
