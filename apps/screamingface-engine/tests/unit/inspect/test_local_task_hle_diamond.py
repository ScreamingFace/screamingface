# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai and inspect_evals, absent in the
# extra-less typecheck install.
"""HLE-Diamond as a LOCAL inspect Task: inspect_evals' hle exam over the Diamond questions.

FEATURE: OME-1863. HLE-Diamond is the authors' cleaned 1,000-question successor to Humanity's
Last Exam. The Task is inspect_evals' own hle Task with one thing swapped, the dataset. What
these tests pin, and why:

- a Diamond row becomes exactly the Sample inspect_evals' hle builds for it (same id, system
  prompt, question, picture and answer key), plus one line of ours: the row's ``partition``
  (reasoning or knowledge) is kept as private Grading Material, so per-half scores can come
  later without changing the Cases;
- the Task reads ``cais/hle-diamond`` at the pinned commit, never ``cais/hle``: a score is
  comparable with the Diamond leaderboard only on Diamond's own questions and answers;
- the Task asks and grades as inspect_evals' hle does: its solver, scorer spec, generation
  settings and epoch reducer are inspect_evals' objects, not copies.

Stand-in: ``datasets.load_dataset`` returns two rows in the Hub's shape (one text, one with a
picture), so no network is touched.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import base64
import functools
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

import datasets  # noqa: E402
from inspect_ai import Task  # noqa: E402
from inspect_ai._util.registry import registry_info  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_evals.hle.dataset import (  # noqa: E402
    record_to_sample as inspect_evals_record_to_sample,
)
from inspect_evals.hle.hle import hle  # noqa: E402

from screamingface_engine_inspect.local_tasks.hle_diamond.hle_diamond import (  # noqa: E402
    DATASET_PATH,
    DATASET_REVISION,
    hle_diamond,
    record_to_sample,
)

#: A one-pixel PNG, as a Diamond row carries a picture: a data URI in the ``image`` column.
_PICTURE: str = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c63f8cfc0f01f0005000201a5f6a1b40000000049454e44ae426082"
    )
).decode("ascii")


def _row(uid: str, question: str, image: str, partition: str) -> dict[str, Any]:
    """One stand-in cais/hle-diamond row in the Hub's shape: cais/hle's columns plus
    ``partition``. Stand-in values, not a real Diamond question."""

    return {
        "id": uid,
        "question": question,
        "image": image,
        "image_preview": None,
        "answer": "42",
        "answer_type": "exactMatch",
        "author_name": "Stand-in author",
        "rationale": "Stand-in rationale",
        "rationale_image": None,
        "raw_subject": "Mathematics",
        "category": "Math",
        "canary": "",
        "partition": partition,
    }


_ROWS: list[dict[str, Any]] = [
    _row("6700a1b2c3d4e5f600000001", "What is 6 times 7?", "", "reasoning"),
    _row("6700a1b2c3d4e5f600000002", "How many pixels are shown?", _PICTURE, "knowledge"),
]


#: The ``scorer`` task argument the ``hle`` row passes: default.yaml's, primary judge only.
_PRIMARY_JUDGE_SPEC: dict[str, Any] = {
    "scorer": "regex_judge",
    "graders": ["grader"],
    "args": {
        "template": "regex_judge_template",
        "instructions": "regex_judge_instructions",
        "max_grader_attempts": 3,
    },
}


def _without_message_ids(sample: Sample) -> list[dict[str, Any]]:
    """The Sample's chat messages as plain data, minus the random id inspect gives each one."""

    assert isinstance(sample.input, list)
    return [message.model_dump(exclude={"id"}) for message in sample.input]


@pytest.fixture
def hub_reads() -> Iterator[list[dict[str, Any]]]:
    """Serve ``_ROWS`` as the Hub dataset and record every ``load_dataset`` call's arguments."""

    calls: list[dict[str, Any]] = []
    real_load_dataset: Any = datasets.load_dataset

    @functools.wraps(real_load_dataset)
    def stand_in_load_dataset(*args: Any, **kwargs: Any) -> Any:
        """Note what was asked for, then hand back the stand-in rows."""

        calls.append({"args": args, **kwargs})
        return datasets.Dataset.from_list(_ROWS)

    with mock.patch.object(datasets, "load_dataset", stand_in_load_dataset):
        yield calls


@pytest.mark.parametrize("row", _ROWS, ids=["text", "picture"])
def test_a_diamond_row_is_inspect_evals_hle_sample_plus_its_partition(
    row: dict[str, Any],
) -> None:
    """Everything the Candidate and the judge read is inspect_evals' own; only the kept
    ``partition`` is added, as the module docstring says."""

    ours: Sample = record_to_sample(row)
    theirs: Sample = inspect_evals_record_to_sample(row)

    assert _without_message_ids(ours) == _without_message_ids(theirs)
    assert ours.target == theirs.target == "42"
    assert ours.metadata == {**(theirs.metadata or {}), "partition": row["partition"]}
    assert ours.id == theirs.id


def test_the_task_reads_cais_hle_diamond_at_the_pinned_commit(
    hub_reads: list[dict[str, Any]],
) -> None:
    """One Hub read, of Diamond's test split at the pinned 40-hex commit, and every row
    becomes a Sample: a Diamond score is comparable only on Diamond's own questions."""

    task: Task = hle_diamond()

    assert DATASET_PATH == "cais/hle-diamond"
    assert len(DATASET_REVISION) == 40
    [call] = hub_reads
    assert call["path"] == DATASET_PATH
    assert call["revision"] == DATASET_REVISION
    assert call["split"] == "test"
    assert [sample.metadata["partition"] for sample in task.dataset] == ["reasoning", "knowledge"]


def test_the_task_asks_and_grades_as_inspect_evals_hle_does(
    hub_reads: list[dict[str, Any]],
) -> None:
    """Same scorer spec in, same scorers, generation settings and epoch reducer out as
    inspect_evals' hle Task, so the marking scheme is theirs at the pinned version."""

    ours: Task = hle_diamond(scorer=_PRIMARY_JUDGE_SPEC)
    theirs: Task = hle(scorer=_PRIMARY_JUDGE_SPEC)

    assert [registry_info(s).name for s in ours.scorer or []] == [
        registry_info(s).name for s in theirs.scorer or []
    ]
    assert ours.config == theirs.config
    assert ours.epochs == theirs.epochs
    assert ours.epochs_reducer is not None and theirs.epochs_reducer is not None
    assert [registry_info(r).name for r in ours.epochs_reducer] == [
        registry_info(r).name for r in theirs.epochs_reducer
    ]
    assert registry_info(ours.solver).name == registry_info(theirs.solver).name


def test_the_importer_names_inspect_evals_own_regex_judge_for_this_local_task(
    hub_reads: list[dict[str, Any]],
) -> None:
    """Our Task builds inspect_evals' ``regex_judge`` through inspect_evals' spec builder, so
    the scorer lives in neither our module nor our package. The importer must name it where it
    is defined, ``inspect_evals.hle.scorers``, the reference the ``hle`` row carries, whose code
    the inspect-evals version pin covers. ``test_a_scorer_from_another_evals_package_is_still_
    refused`` (test_hle_importer_scorer.py) keeps the old refusal for an inspect_evals Task."""

    import importlib

    from screamingface_engine_inspect.importer import _resolve_scorer

    [judge] = hle_diamond(scorer=_PRIMARY_JUDGE_SPEC).scorer or []
    module: Any = importlib.import_module(
        "screamingface_engine_inspect.local_tasks.hle_diamond.hle_diamond"
    )

    reference, _, name = _resolve_scorer(judge, module)

    assert (reference, name) == ("inspect_evals.hle.scorers:regex_judge", "regex_judge")
