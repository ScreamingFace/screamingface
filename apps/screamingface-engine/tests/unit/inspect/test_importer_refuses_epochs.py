# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The importer refuses a Task that asks each Sample several times (OME-1458, PR 2 of 7).

FEATURE: several Attempts per Case. An inspect Task may declare ``epochs=N``: run every
Sample N times and fold the N scores with a reducer (MBPP: 5 epochs, ``pass_at_1``;
ZeroBench: 5 epochs, ``pass_at_5``). The Engine asks each Case once, so importing such a
Task would publish a one-Attempt score as the eval's number, silently.

INVARIANT: until the Engine runs several Attempts per Case (the build ticket, spec
``docs/spec/2026-10-07-OME-1458-attempts-per-case.md`` D12), a Task declaring more than one
epoch is refused, naming the epoch count and the reducer, whatever the reducer is. A Task
declaring one epoch, with or without a reducer, imports exactly as before.

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
#: in the epochs it declares: `any_of_two` stands in for an ARC-style any-match Task (the
#: shape the build will accept), `mbpp_like` for MBPP's averaged five epochs with no reducer
#: named, `lab_bench_like` for lab_bench's `Epochs(1, "mode")`.
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


def test_an_any_match_task_with_two_epochs_is_refused_until_attempts_exist(
    fake_eval: str,
) -> None:
    # WHY refused although the build will accept this exact shape: today there is nowhere to
    # send a second Attempt, so importing it would publish the first Attempt's score.
    with pytest.raises(TaskReplayError, match=r"epochs=2.*pass_at_2"):
        replay_for_import(f"{fake_eval}:any_of_two", None)


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


def test_a_task_declaring_no_epochs_imports_as_before(fake_eval: str) -> None:
    replay: ImportReplay = replay_for_import(f"{fake_eval}:no_epochs", None)

    assert replay.facts.scorer == "inspect_ai.scorer:match"
