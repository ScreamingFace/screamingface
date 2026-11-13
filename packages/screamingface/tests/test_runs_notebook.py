"""The Runs notebook uses the public API without spending or cancelling by default."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_BUILDER = Path(__file__).parent.parent / "scripts" / "build_notebooks.py"


def _notebook() -> Any:
    notebooks = runpy.run_path(str(_BUILDER))["notebooks"]()
    assert "20_runs.ipynb" in notebooks, "the generated Runs demo is missing"
    return notebooks["20_runs.ipynb"]


def _code_cells() -> list[str]:
    return [cell.source for cell in _notebook().cells if cell.cell_type == "code"]


def test_runs_notebook_teaches_the_public_runs_workflow() -> None:
    source = "\n".join(_code_cells())

    for api in (
        "sf.runs.list(",
        "sf.runs.get(",
        "run.progress()",
        "run.wait(",
        "reopened_run.report()",
        "run_to_cancel.cancel()",
    ):
        assert api in source


def test_paid_evaluation_is_opt_in() -> None:
    source = next(cell for cell in _code_cells() if "RUN_EVALUATION = False" in cell)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    sf = SimpleNamespace(
        Model=lambda *args, **kwargs: "model",
        evaluate=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    exec(source, {"sf": sf})  # noqa: S102 -- execute the authored gate with a local stub
    assert calls == []

    exec(source.replace("RUN_EVALUATION = False", "RUN_EVALUATION = True", 1), {"sf": sf})  # noqa: S102
    assert len(calls) == 1


def test_cancellation_requires_an_explicit_run_id() -> None:
    source = next(cell for cell in _code_cells() if "CANCEL_RUN_ID = None" in cell)
    get_calls: list[str] = []
    cancel_calls: list[str] = []
    run = SimpleNamespace(cancel=lambda: cancel_calls.append("cancelled"))
    sf = SimpleNamespace(runs=SimpleNamespace(get=lambda run_id: get_calls.append(run_id) or run))

    exec(source, {"sf": sf})  # noqa: S102 -- execute the authored gate with a local stub
    assert get_calls == []
    assert cancel_calls == []

    exec(
        source.replace("CANCEL_RUN_ID = None", 'CANCEL_RUN_ID = "run_demo"', 1),
        {"sf": sf},
    )  # noqa: S102
    assert get_calls == ["run_demo"]
    assert cancel_calls == ["cancelled"]
