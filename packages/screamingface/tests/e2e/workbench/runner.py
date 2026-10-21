"""Execute one workbench notebook with injected parameters (e2e workbench spec §3.2).

INVARIANT: a failed cell never loses the evidence — the executed notebook (with the traceback
in its outputs) is returned together with the error text, and the caller writes both.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError, CellTimeoutError, DeadKernelError

RESULT_PREFIX = "WORKBENCH_RESULT="
_KERNEL = "sf-workbench"

DEADLINE_ENV = "SCREAMINGFACE_WORKBENCH_DEADLINE_S"
# WHY 600: the CI job is capped at 30 min (screamingface-e2e-replay.yml) and its whole e2e
# pytest step takes ~7 min today; 10 min for one notebook leaves room for a cold asset cache
# and still ends the notebook — and writes its bundle — well before the job is killed.
_DEFAULT_DEADLINE_S = 600


def notebook_deadline_s() -> int:
    """The whole-notebook deadline in seconds: ``SCREAMINGFACE_WORKBENCH_DEADLINE_S`` or 600."""
    raw = os.environ.get(DEADLINE_ENV)
    if raw is None or raw == "":
        return _DEFAULT_DEADLINE_S
    if not (raw.isascii() and raw.isdigit()) or int(raw) <= 0:
        raise ValueError(f"{DEADLINE_ENV}={raw!r} must be a positive whole number of seconds")
    return int(raw)


@dataclass(frozen=True)
class NotebookRun:
    executed: nbformat.NotebookNode  # always present, outputs included
    result: dict[str, Any] | None  # parsed WORKBENCH_RESULT payload, None if never printed
    error: str | None  # cell traceback text, None on success


def _is_literal(value: Any) -> bool:
    """JSON-like values only, checked recursively, so ``repr`` always round-trips as source."""
    match value:
        case str() | int() | None:  # bool is an int
            ok = True
        case float():
            ok = math.isfinite(value)  # repr(nan) is not valid source
        case list():
            ok = all(_is_literal(v) for v in value)  # pyright: ignore[reportUnknownVariableType]
        case dict():
            items: dict[Any, Any] = value  # pyright: ignore[reportUnknownVariableType]
            ok = all(isinstance(k, str) and _is_literal(v) for k, v in items.items())
        case _:
            ok = False
    return ok


def _literal(name: str, value: Any) -> str:
    if not name.isidentifier():
        raise ValueError(f"parameter name {name!r} is not a Python identifier")
    if not _is_literal(value):
        raise TypeError(f"parameter {name} must be a JSON-like literal, got {type(value)!r}")
    return f"{name} = {value!r}"


def _inject(nb: nbformat.NotebookNode, params: Mapping[str, Any]) -> None:
    index = next(
        (i for i, c in enumerate(nb.cells) if "parameters" in c.metadata.get("tags", [])), None
    )
    if index is None:
        raise ValueError("notebook has no cell tagged 'parameters'")
    cell = nbformat.v4.new_code_cell("\n".join(_literal(k, v) for k, v in params.items()))
    cell.metadata["tags"] = ["injected-parameters"]
    nb.cells.insert(index + 1, cell)


@contextmanager
def _private_kernelspec() -> Iterator[None]:
    """WHY: a user-level `python3` kernelspec may point at another interpreter; the workbench
    must execute with THIS venv's SDK, so it registers its own spec in a throwaway dir."""
    with tempfile.TemporaryDirectory() as root:
        spec_dir = Path(root) / "kernels" / _KERNEL
        spec_dir.mkdir(parents=True)
        (spec_dir / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                    "display_name": _KERNEL,
                    "language": "python",
                }
            )
        )
        previous = os.environ.get("JUPYTER_PATH")
        os.environ["JUPYTER_PATH"] = root + (os.pathsep + previous if previous else "")
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("JUPYTER_PATH", None)
            else:
                os.environ["JUPYTER_PATH"] = previous


def _parse(payload: str) -> tuple[dict[str, Any] | None, str | None]:
    """A ``WORKBENCH_RESULT`` payload as a dict, or ``None`` and why it is malformed."""
    why = f"malformed {RESULT_PREFIX[:-1]} payload"
    try:
        value: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"{why}: not valid JSON ({exc})"
    if not isinstance(value, dict):
        return None, f"{why}: not a JSON object ({type(value).__name__})"
    return value, None  # pyright: ignore[reportUnknownVariableType]


def _result(nb: nbformat.NotebookNode) -> tuple[dict[str, Any] | None, str | None]:
    """The first ``WORKBENCH_RESULT=`` payload and, if it is malformed, why (never raises)."""
    for cell in nb.cells:
        if "workbench-result" not in cell.metadata.get("tags", []):
            continue
        for output in cell.get("outputs", []):
            for line in str(output.get("text", "")).splitlines():
                if line.startswith(RESULT_PREFIX):
                    return _parse(line[len(RESULT_PREFIX) :])
    return None, None


def run_notebook(
    path: Path,
    params: Mapping[str, Any],
    *,
    timeout_s: int = 900,
    deadline_s: int = _DEFAULT_DEADLINE_S,
) -> NotebookRun:
    """Run ``path`` with ``params`` injected after its ``parameters`` cell.

    ``timeout_s`` bounds one cell; ``deadline_s`` bounds the WHOLE notebook (gap b): nbclient
    only knows per-cell timeouts, so each cell's timeout is capped at what is left of the
    deadline. A run stopped by it is an ordinary execution failure that names the deadline.

    Raises only for caller mistakes (no parameters cell, non-literal parameter); every
    execution failure — a failing cell, a cell timeout, the notebook deadline, a dead kernel,
    a malformed ``WORKBENCH_RESULT`` payload — is returned in ``NotebookRun.error`` alongside
    the (partially) executed notebook.
    """
    nb = nbformat.read(path, as_version=4)
    _inject(nb, params)
    deadline = time.monotonic() + deadline_s
    capped = False

    def cell_timeout(cell: nbformat.NotebookNode) -> int:
        nonlocal capped
        left = math.ceil(deadline - time.monotonic())
        capped = left < timeout_s
        return max(1, min(timeout_s, left))

    error: str | None = None
    with _private_kernelspec():
        client = NotebookClient(
            nb,
            kernel_name=_KERNEL,
            timeout=timeout_s,
            timeout_func=cell_timeout,
            resources={"metadata": {"path": str(path.parent)}},
        )
        try:
            client.execute()
        except (CellExecutionError, CellTimeoutError, DeadKernelError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, CellTimeoutError) and capped:
                # Last line on purpose: the verdict surfaces it as the root cause.
                error += f"\nnotebook deadline of {deadline_s}s exceeded across all cells"
    result, malformed = _result(nb)
    if malformed:
        # The cell error stays last: callers surface the last line as the root cause.
        error = malformed if error is None else f"{malformed}\n{error}"
    return NotebookRun(executed=nb, result=result, error=error)
