# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The importer maps any-match epochs to Attempts and refuses every other reducer (OME-1458).

FEATURE: several Attempts per Case. An inspect Task may declare ``epochs=N``: run every
Sample N times and fold the N scores with a reducer (MBPP: 5 epochs, ``pass_at_1``;
ZeroBench: 5 epochs, ``pass_at_5``). The Engine asks each Case N times and marks a Check met
if any Attempt met it, which is what ``max``, ``at_least_1`` and ``pass_at_N`` compute.

INVARIANT: a Task whose every reducer is any-match at N imports as ``attempts=N``; any other
reducer is refused by name, because importing it would publish a different number from the
eval's (spec ``docs/spec/2026-10-07-OME-1458-attempts-per-case.md`` §2.6). A Task declaring
one epoch, with or without a reducer, imports exactly as before.

The tests run the real import child on a stand-in eval written to tmp_path (the
test_importer_named_scores pattern): they prove the child reads ``epochs`` off the built
Task, not how any real eval fetches its Samples.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.import_replay import (  # noqa: E402
    ImportReplay,
    replay_for_import,
)
from screamingface_engine_inspect.task_replay import TaskReplayError  # noqa: E402

#: A stand-in eval. Each task is the same one-Sample-per-row exact-match Task, differing only
#: in the epochs it declares: `any_of_two`, `max_of_two` and `at_least_one_of_three` stand in
#: for ARC-style any-match Tasks, `pass_at_one_of_five` for MBPP's estimator, `mbpp_like` for
#: averaged epochs with no reducer named, `lab_bench_like` for lab_bench's `Epochs(1, "mode")`.
FAKE_EVAL: str = textwrap.dedent(
    """
    import os
    from inspect_ai import Epochs, Task, task
    from inspect_ai.dataset import FieldSpec, json_dataset
    from inspect_ai.scorer import match
    from inspect_ai.solver import generate, prompt_template

    DATA = os.environ["FAKE_EPOCHS_DATA"]

    def _task(**epochs):
        return Task(dataset=json_dataset(DATA, FieldSpec(input="q", target="a", id="id")),
                    solver=[prompt_template("Answer briefly.\\n\\n{prompt}\\n"), generate()],
                    scorer=match(), **epochs)

    @task
    def any_of_two() -> Task:
        return _task(epochs=Epochs(2, "pass_at_2"))

    @task
    def max_of_two() -> Task:
        return _task(epochs=Epochs(2, "max"))

    @task
    def at_least_one_of_three() -> Task:
        return _task(epochs=Epochs(3, "at_least_1"))

    @task
    def pass_at_one_of_five() -> Task:
        return _task(epochs=Epochs(5, "pass_at_1"))

    @task
    def any_of_five_and_mean() -> Task:
        return _task(epochs=Epochs(5, ["pass_at_5", "mean"]))

    @task
    def mbpp_like() -> Task:
        return _task(epochs=5)

    @task
    def lab_bench_like() -> Task:
        return _task(epochs=Epochs(1, "mode"))

    @task
    def no_epochs() -> Task:
        return _task()
    """
)

_ROWS: list[dict[str, object]] = [
    {"id": 1, "q": "What is 6 times 7?", "a": "42"},
    {"id": 2, "q": "What is 2 plus 2?", "a": "4"},
]


@pytest.fixture
def fake_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write the stand-in eval where the import child can import it; return its module name."""

    (tmp_path / "fake_epochs_eval.py").write_text(FAKE_EVAL, encoding="utf-8")
    (tmp_path / "cases.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in _ROWS), encoding="utf-8"
    )
    monkeypatch.setenv("FAKE_EPOCHS_DATA", str(tmp_path / "cases.jsonl"))
    existing: str | None = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) if not existing else f"{tmp_path}{os.pathsep}{existing}"
    )
    return "fake_epochs_eval"


@pytest.mark.parametrize(
    ("task_name", "attempts"),
    [("any_of_two", 2), ("max_of_two", 2), ("at_least_one_of_three", 3)],
)
def test_an_any_match_task_imports_as_that_many_attempts(
    fake_eval: str, task_name: str, attempts: int
) -> None:
    # WHY these three: at N epochs each computes "correct if any epoch was", the any-of-N
    # number the Engine's per-Check fold publishes.
    replay: ImportReplay = replay_for_import(f"{fake_eval}:{task_name}", None)

    assert replay.facts.attempts == attempts


def test_pass_at_one_of_five_is_refused_naming_the_reducer(fake_eval: str) -> None:
    # WHY: inspect's pass_at_1 over 5 epochs is the unbiased estimator, a different number
    # from any-of-5 (MBPP's shape), so importing it would publish the wrong score.
    with pytest.raises(TaskReplayError, match=r"epochs=5 with reducer pass_at_1"):
        replay_for_import(f"{fake_eval}:pass_at_one_of_five", None)


def test_one_non_any_match_reducer_refuses_the_whole_task(fake_eval: str) -> None:
    # WHY: inspect publishes every declared reducer; one of them averaging is a number the
    # Engine would not reproduce, so the Task is refused, naming only the offending reducer.
    with pytest.raises(TaskReplayError, match=r"epochs=5 with reducer mean:"):
        replay_for_import(f"{fake_eval}:any_of_five_and_mean", None)


def test_a_task_averaging_five_epochs_is_refused_naming_inspects_default_reducer(
    fake_eval: str,
) -> None:
    # WHY name `mean`: a Task that names no reducer is still folded, by inspect's default;
    # the reader must see which number the eval publishes.
    with pytest.raises(TaskReplayError, match=r"epochs=5.*mean"):
        replay_for_import(f"{fake_eval}:mbpp_like", None)


def test_one_epoch_with_a_reducer_imports_as_before(fake_eval: str) -> None:
    # INVARIANT: one epoch is one Attempt, whatever reducer folds it (lab_bench's shape).
    replay: ImportReplay = replay_for_import(f"{fake_eval}:lab_bench_like", None)

    assert replay.facts.scorer == "inspect_ai.scorer:match"
    assert replay.facts.attempts == 1


def test_a_task_declaring_no_epochs_imports_as_before(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:no_epochs", None)

    assert replay.facts.scorer == "inspect_ai.scorer:match"
