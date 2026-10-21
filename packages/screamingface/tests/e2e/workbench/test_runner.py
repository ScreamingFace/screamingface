from __future__ import annotations

import sys
import time
from pathlib import Path

import nbformat
import pytest

from workbench.runner import DEADLINE_ENV, RESULT_PREFIX, notebook_deadline_s, run_notebook


def _write(tmp_path: Path, *cells: nbformat.NotebookNode) -> Path:
    nb = nbformat.v4.new_notebook(cells=list(cells))
    path = tmp_path / "nb.ipynb"
    nbformat.write(nb, path)
    return path


def _params(source: str) -> nbformat.NotebookNode:
    cell = nbformat.v4.new_code_cell(source)
    cell.metadata["tags"] = ["parameters"]
    return cell


def _result(source: str) -> nbformat.NotebookNode:
    cell = nbformat.v4.new_code_cell(source)
    cell.metadata["tags"] = ["workbench-result"]
    return cell


def test_injected_parameters_override_defaults_and_result_is_parsed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _params("X = 1\nNAME = 'default'"),
        _result(f"import json; print('{RESULT_PREFIX}' + json.dumps({{'x': X, 'name': NAME}}))"),
    )
    run = run_notebook(path, {"X": 5, "NAME": "replay"})
    assert run.error is None
    assert run.result == {"x": 5, "name": "replay"}
    tags = [c.metadata.get("tags", []) for c in run.executed.cells]
    assert ["injected-parameters"] in tags


def test_a_failing_cell_returns_the_executed_notebook_and_the_error(tmp_path: Path) -> None:
    path = _write(tmp_path, _params("X = 1"), nbformat.v4.new_code_cell("assert X == 2, 'band'"))
    run = run_notebook(path, {})
    assert run.error is not None and "band" in run.error
    assert run.result is None
    assert any(o.get("output_type") == "error" for o in run.executed.cells[-1].outputs)


@pytest.mark.parametrize(
    "value", [object(), [1, object()], {"k": object()}, {1: "non-str key"}, float("nan")]
)
def test_unsupported_parameter_types_are_refused(tmp_path: Path, value: object) -> None:
    path = _write(tmp_path, _params("X = 1"))
    with pytest.raises(TypeError, match="X"):
        run_notebook(path, {"X": value})


def test_a_notebook_without_a_parameters_cell_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, nbformat.v4.new_code_cell("1"))
    with pytest.raises(ValueError, match="parameters"):
        run_notebook(path, {})


@pytest.mark.parametrize(
    ("payload", "why"), [("{not json", "not valid JSON"), ("[1, 2]", "not a JSON object")]
)
def test_a_malformed_result_payload_is_an_error_not_a_raise(
    tmp_path: Path, payload: str, why: str
) -> None:
    path = _write(tmp_path, _params("X = 1"), _result(f"print({RESULT_PREFIX + payload!r})"))
    run = run_notebook(path, {})
    assert run.result is None
    assert run.error is not None and "WORKBENCH_RESULT" in run.error and why in run.error
    assert run.executed.cells[-1].outputs, "the executed notebook (with outputs) is kept"


def test_a_malformed_payload_keeps_the_cell_error_last(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _params("X = 1"),
        _result(f"print({RESULT_PREFIX + '{bad'!r})"),
        nbformat.v4.new_code_cell("assert X == 2, 'band'"),
    )
    run = run_notebook(path, {})
    assert run.result is None
    assert run.error is not None and "not valid JSON" in run.error
    assert "band" in run.error.strip().splitlines()[-1]


def test_the_whole_notebook_has_one_deadline_across_cells(tmp_path: Path) -> None:
    """Gap (b): nbclient's timeout is per cell, so N slow cells could outlive the CI job and
    no bundle would be written. The deadline spans the notebook and still returns the run."""
    slow = [nbformat.v4.new_code_cell("import time; time.sleep(2)") for _ in range(4)]
    path = _write(tmp_path, _params("X = 1"), *slow)
    started = time.monotonic()
    run = run_notebook(path, {}, timeout_s=60, deadline_s=3)
    elapsed = time.monotonic() - started
    # 4 x 2s of cells against a 3s budget: stopped in the second cell, not after all four.
    assert elapsed < 7.5, elapsed
    assert run.error is not None and "deadline" in run.error and "3s" in run.error
    assert run.executed.cells, "the executed notebook is kept for the bundle"


def test_a_notebook_within_its_deadline_is_untouched(tmp_path: Path) -> None:
    path = _write(tmp_path, _params("X = 1"), _result(f"print({RESULT_PREFIX + '{}'!r})"))
    run = run_notebook(path, {}, timeout_s=60, deadline_s=60)
    assert run.error is None and run.result == {}


def test_the_kernel_runs_on_this_interpreter(tmp_path: Path) -> None:
    """Review Focus 4: a user-level ``python3`` kernelspec must not win over the SDK venv."""
    path = _write(
        tmp_path,
        _params("X = 1"),
        _result(
            f"import json, sys; print('{RESULT_PREFIX}' + json.dumps({{'exe': sys.executable}}))"
        ),
    )
    run = run_notebook(path, {})
    assert run.error is None
    assert run.result == {"exe": sys.executable}


def test_the_lane_deadline_defaults_inside_the_ci_job_and_is_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DEADLINE_ENV, raising=False)
    # The CI job is capped at 30 min and the whole e2e pytest step takes ~7 min today.
    assert notebook_deadline_s() == 600
    monkeypatch.setenv(DEADLINE_ENV, "1200")
    assert notebook_deadline_s() == 1200


@pytest.mark.parametrize("bad", ["0", "-5", "ten", "1.5"])
def test_a_bad_lane_deadline_is_refused(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv(DEADLINE_ENV, bad)
    with pytest.raises(ValueError, match=DEADLINE_ENV):
        notebook_deadline_s()
