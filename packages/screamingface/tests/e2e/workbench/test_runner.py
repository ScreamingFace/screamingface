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
    path = _write(
        tmp_path,
        _params("X = 1"),
        nbformat.v4.new_code_cell("assert X == 2, 'band'"),
        _result(f"print({RESULT_PREFIX + '{}'!r})"),
    )
    run = run_notebook(path, {})
    assert run.error is not None and "band" in run.error
    assert run.result is None
    assert any(o.get("output_type") == "error" for o in run.executed.cells[-2].outputs)


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
    path = _write(tmp_path, _params("X = 1"), *slow, _result(f"print({RESULT_PREFIX + '{}'!r})"))
    started = time.monotonic()
    run = run_notebook(path, {}, timeout_s=60, deadline_s=3)
    elapsed = time.monotonic() - started
    # 4 x 2s of cells against a 3s budget: stopped in the second cell, not after all four.
    assert elapsed < 7.5, elapsed
    assert run.error is not None and "deadline" in run.error and "3s" in run.error
    assert run.executed.cells, "the executed notebook is kept for the bundle"


def test_the_deadline_stops_many_short_cells_before_the_next_one_starts(tmp_path: Path) -> None:
    """Review re-finding 2: the deadline is cumulative, not a per-cell clamp. 30 cells of 0.2s
    each fit any per-cell timeout, but together outlive a 1s deadline; no further cell may
    start once it has passed, and the partially executed notebook is kept."""
    short = [nbformat.v4.new_code_cell("import time; time.sleep(0.2)") for _ in range(30)]
    path = _write(tmp_path, _params("X = 1"), *short, _result(f"print({RESULT_PREFIX + '{}'!r})"))
    started = time.monotonic()
    run = run_notebook(path, {}, timeout_s=60, deadline_s=1)
    elapsed = time.monotonic() - started
    # Uncapped, the 30 cells alone take 6s; the deadline (1s, kernel start included) stops it.
    assert elapsed < 4.5, elapsed
    assert run.error is not None
    assert run.error.strip().splitlines()[-1] == (
        "notebook deadline of 1s exceeded across all cells"
    )
    assert run.result is None
    assert not run.executed.cells[-1].get("outputs"), "the result cell never started"
    assert run.executed.cells[-1].get("execution_count") is None
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


# Review finding 6: exactly one result cell and exactly one WORKBENCH_RESULT= marker, or the run
# fails closed — never "first marker wins".


@pytest.mark.parametrize("cells", [0, 2], ids=["no-result-cell", "two-result-cells"])
def test_a_notebook_without_exactly_one_result_cell_is_refused(tmp_path: Path, cells: int) -> None:
    result = [_result(f"print({RESULT_PREFIX + '{}'!r})") for _ in range(cells)]
    path = _write(tmp_path, _params("X = 1"), *result)
    with pytest.raises(ValueError, match=f"exactly one.*workbench-result.*found {cells}"):
        run_notebook(path, {})


def test_two_markers_in_the_result_cell_fail_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _params("X = 1"),
        _result(f"print({RESULT_PREFIX + '{"a": 1}'!r}); print({RESULT_PREFIX + '{}'!r})"),
    )
    run = run_notebook(path, {})
    assert run.result is None, "no marker may win when there are two"
    assert run.error is not None and "exactly one WORKBENCH_RESULT= marker" in run.error
    assert "found 2" in run.error


def test_a_marker_printed_outside_the_result_cell_fails_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _params("X = 1"),
        nbformat.v4.new_code_cell(f"print({RESULT_PREFIX + '{"forged": 1}'!r})"),
        _result(f"print({RESULT_PREFIX + '{}'!r})"),
    )
    run = run_notebook(path, {})
    assert run.result is None
    assert run.error is not None
    assert "outside the 'workbench-result' cell" in run.error


def test_a_forged_marker_is_never_taken_when_the_result_cell_prints_none(tmp_path: Path) -> None:
    """Review re-finding 3: markers are bound to the ``workbench-result`` cell. Before, a
    marker printed by ANOTHER cell was accepted when the result cell printed nothing."""
    path = _write(
        tmp_path,
        _params("X = 1"),
        nbformat.v4.new_code_cell(f"print({RESULT_PREFIX + '{"forged": 1}'!r})"),
        _result("pass"),
    )
    run = run_notebook(path, {})
    assert run.result is None, "a marker from another cell must never become the result"
    assert run.error is not None
    assert "outside the 'workbench-result' cell" in run.error


def test_a_duplicate_marker_keeps_the_cell_error_last(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _params("X = 1"),
        _result(f"print({RESULT_PREFIX + '{}'!r}); print({RESULT_PREFIX + '{}'!r})"),
        nbformat.v4.new_code_cell("assert X == 2, 'band'"),
    )
    run = run_notebook(path, {})
    assert run.result is None
    assert run.error is not None and "found 2" in run.error
    assert "band" in run.error.strip().splitlines()[-1]
