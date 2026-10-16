from __future__ import annotations

from pathlib import Path

import nbformat
import pytest

from workbench.runner import RESULT_PREFIX, run_notebook


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
