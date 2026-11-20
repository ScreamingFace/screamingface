"""The Runs notebook uses the public API without spending or cancelling by default."""

from __future__ import annotations

import runpy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_BUILDER = Path(__file__).parent.parent / "scripts" / "build_notebooks.py"


def _notebook() -> Any:
    notebooks = runpy.run_path(str(_BUILDER))["notebooks"]()
    assert "21_runs.ipynb" in notebooks, "the generated Runs demo is missing"
    return notebooks["21_runs.ipynb"]


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


def _detach_cell() -> str:
    return next(cell for cell in _code_cells() if "RUN_DETACHED = False" in cell)


def _reattach_cell() -> str:
    return next(cell for cell in _code_cells() if "sf.runs.get(REATTACH_RUN_ID).wait()" in cell)


def _sf_starting(calls: list[dict[str, object]]) -> SimpleNamespace:
    run = SimpleNamespace(id="run_demo", detached=True, deadline_at=None)
    return SimpleNamespace(
        Model=lambda *args, **kwargs: "model",
        evaluate=lambda *args, **kwargs: calls.append(kwargs) or run,
    )


def test_a_detached_run_is_opt_in() -> None:
    calls: list[dict[str, object]] = []

    exec(_detach_cell(), {"sf": _sf_starting(calls)})  # noqa: S102 -- the authored gate, stubbed
    assert calls == []

    exec(  # noqa: S102
        _detach_cell().replace("RUN_DETACHED = False", "RUN_DETACHED = True", 1),
        {"sf": _sf_starting(calls)},
    )
    assert len(calls) == 1
    assert calls[0]["detach"] is True
    assert calls[0]["deadline"] == timedelta(hours=2)


def test_a_reattach_id_starts_no_new_run_even_with_the_detached_flag_on() -> None:
    calls: list[dict[str, object]] = []
    source = (
        _detach_cell()
        .replace("RUN_DETACHED = False", "RUN_DETACHED = True", 1)
        .replace("REATTACH_RUN_ID = None", 'REATTACH_RUN_ID = "run_demo"', 1)
    )

    exec(source, {"sf": _sf_starting(calls)})  # noqa: S102 -- the authored gate, stubbed
    assert calls == []


def test_reattaching_needs_an_id_and_shows_the_runs_report() -> None:
    get_calls: list[str] = []
    run = SimpleNamespace(wait=lambda: "report")
    sf = SimpleNamespace(
        runs=SimpleNamespace(get=lambda run_id: get_calls.append(run_id) or run),
        ExecutionError=RuntimeError,
    )

    scope: dict[str, object] = {"sf": sf, "REATTACH_RUN_ID": None}
    exec(_reattach_cell(), scope)  # noqa: S102 -- the authored gate, stubbed
    assert get_calls == []

    scope = {"sf": sf, "REATTACH_RUN_ID": "run_demo"}
    exec(_reattach_cell(), scope)  # noqa: S102
    assert get_calls == ["run_demo"]
    assert scope["reattached_report"] == "report"


def test_an_unknown_reattach_id_reads_as_a_message() -> None:
    def unknown(run_id: str) -> object:
        raise KeyError(run_id)

    sf = SimpleNamespace(runs=SimpleNamespace(get=unknown), ExecutionError=RuntimeError)
    scope: dict[str, object] = {"sf": sf, "REATTACH_RUN_ID": "run_missing"}

    exec(_reattach_cell(), scope)  # noqa: S102 -- the authored gate, stubbed
    assert scope["reattached_report"] == "No Run run_missing for this owner."
