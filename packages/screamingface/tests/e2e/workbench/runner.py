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


RESULT_TAG = "workbench-result"


def _require_one_result_cell(nb: nbformat.NotebookNode) -> None:
    found = sum(RESULT_TAG in c.metadata.get("tags", []) for c in nb.cells)
    if found != 1:
        raise ValueError(
            f"notebook must have exactly one cell tagged {RESULT_TAG!r}, found {found}"
        )


def _markers(nb: nbformat.NotebookNode) -> tuple[list[str], list[int]]:
    """``WORKBENCH_RESULT=`` payloads of the ``workbench-result`` cell, in order, and the
    indices of any OTHER cell that printed the marker (review re-finding 3: bound to one cell)."""
    payloads: list[str] = []
    strays: list[int] = []
    for index, cell in enumerate(nb.cells):
        found = [
            line[len(RESULT_PREFIX) :]
            for output in cell.get("outputs", [])
            for line in str(output.get("text", "")).splitlines()
            if line.startswith(RESULT_PREFIX)
        ]
        if RESULT_TAG in cell.metadata.get("tags", []):
            payloads += found
        elif found:
            strays.append(index)
    return payloads, strays


def _result(nb: nbformat.NotebookNode) -> tuple[dict[str, Any] | None, str | None]:
    """The single ``WORKBENCH_RESULT=`` payload and, if it is unusable, why (never raises).

    Fails closed (review finding 6, re-finding 3): only the ``workbench-result`` cell may print
    the marker, exactly once. A marker from any other cell, or a second one, makes the result
    untrustworthy, so none is taken. None printed is not an error here; ``result_check``
    reports the missing result.
    """
    payloads, strays = _markers(nb)
    if strays:
        return None, (
            f"{RESULT_PREFIX} marker printed outside the {RESULT_TAG!r} cell "
            f"(cell index {', '.join(map(str, strays))})"
        )
    if len(payloads) > 1:
        return None, (
            f"notebook must print exactly one {RESULT_PREFIX} marker, found {len(payloads)}"
        )
    return _parse(payloads[0]) if payloads else (None, None)


class _DeadlineExceededError(Exception):
    """Raised before a cell starts once the whole-notebook deadline has passed."""


class _DeadlineClient(NotebookClient):
    """WHY: nbclient only bounds one cell at a time; a hard stop before each cell is what
    makes the deadline cumulative (review re-finding 2: N short cells each under the clamp)."""

    deadline: float = math.inf

    async def async_execute_cell(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, cell: nbformat.NotebookNode, cell_index: int, *args: Any, **kwargs: Any
    ) -> nbformat.NotebookNode:
        if cell.cell_type == "code" and time.monotonic() >= self.deadline:
            raise _DeadlineExceededError(f"stopped before cell index {cell_index}")
        return await super().async_execute_cell(cell, cell_index, *args, **kwargs)


def _execute(
    nb: nbformat.NotebookNode, cwd: Path, *, timeout_s: int, deadline_s: int
) -> str | None:
    """Execute ``nb`` in place under one whole-notebook deadline; the error text, or ``None``."""
    deadline = time.monotonic() + deadline_s
    deadline_error = f"notebook deadline of {deadline_s}s exceeded across all cells"
    capped = False

    def cell_timeout(cell: nbformat.NotebookNode) -> int:
        nonlocal capped
        left = math.ceil(deadline - time.monotonic())
        capped = left < timeout_s
        return max(1, min(timeout_s, left))

    with _private_kernelspec():
        client = _DeadlineClient(
            nb,
            kernel_name=_KERNEL,
            timeout=timeout_s,
            timeout_func=cell_timeout,
            resources={"metadata": {"path": str(cwd)}},
        )
        client.deadline = deadline
        try:
            client.execute()
        except _DeadlineExceededError as exc:
            # Last line on purpose: the verdict surfaces it as the root cause.
            return f"{exc}\n{deadline_error}"
        except (CellExecutionError, CellTimeoutError, DeadKernelError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, CellTimeoutError) and capped:
                error += f"\n{deadline_error}"
            return error
    return None


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
    deadline, and no cell starts once it has passed. A run stopped by it is an ordinary
    execution failure that names the deadline; the partially executed notebook is kept.

    Raises only for caller mistakes (no parameters cell, not exactly one ``workbench-result``
    cell, non-literal parameter); every execution failure — a failing cell, a cell timeout,
    the notebook deadline, a dead kernel, a malformed or repeated ``WORKBENCH_RESULT`` marker —
    is returned in ``NotebookRun.error`` alongside
    the (partially) executed notebook.
    """
    nb = nbformat.read(path, as_version=4)
    _inject(nb, params)
    _require_one_result_cell(nb)
    error = _execute(nb, path.parent, timeout_s=timeout_s, deadline_s=deadline_s)
    result, malformed = _result(nb)
    if malformed:
        # The cell error stays last: callers surface the last line as the root cause.
        error = malformed if error is None else f"{malformed}\n{error}"
    return NotebookRun(executed=nb, result=result, error=error)
