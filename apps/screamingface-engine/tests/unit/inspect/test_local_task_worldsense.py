# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""WorldSense as a LOCAL Task: every trial kept, inspect_evals PR #2507 adopted as our own.

What these tests pin, and why:

- each trial is named by its own `Key`, so the three trials of one described world are three
  Cases; everything else in the Sample is inspect_evals';
- the whole pinned file gives 87,048 Cases, every gold answer of each family in the dataset's
  own balance (the balance is how the paper cancels a model that always says "TRUE");
- the TRIPWIRES assert inspect_evals v0.20.0 still names every trial of a world alike and still
  keeps 40,176, all on the "yes" side: when the inspect_evals pin reaches the fix, they fail
  and say to point the row back at inspect_evals' Task
  (https://github.com/UKGovernmentBEIS/inspect_evals/pull/2507);
- the row serves the local Task as ours (catalogue id without the `inspect-` prefix).

The two whole-file tests read the sha256-pinned `trials.jsonl.bz2` through inspect_evals' own
loader, which downloads it once (3 MB, GitHub) into the inspect_evals cache.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.dataset import Dataset, Sample  # noqa: E402
from inspect_evals.worldsense.worldsense import (  # noqa: E402
    load_worldsense_dataset,
)
from inspect_evals.worldsense.worldsense import (  # noqa: E402
    record_to_sample as inspect_evals_record_to_sample,
)

from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402
from screamingface_engine_inspect.local_tasks.worldsense.worldsense import (  # noqa: E402
    record_to_sample,
    worldsense,
)
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES  # noqa: E402

_PR: str = "https://github.com/UKGovernmentBEIS/inspect_evals/pull/2507"
_TUPLE: str = "fast_spec_r5_seed06_results_10-11-2023_10h36m12s_6109"
_SETUP: str = (
    "Alice is enrolled in 3 courses per week: Alice takes history before computer science "
    "and economics before history. \nChoose one of the following alternatives: (1) Alice "
    "takes {x} in between {y} and computer science, (2) Alice takes {x} outside of the time "
    "range between {y} and computer science, or (3) it is impossible to decide.\nThink "
    "carefully, and only respond with one of these possible options (1), (2), or (3)."
)


def _trial(key: int, x: str, y: str, gold: str) -> dict[str, Any]:
    """One trial of the file's first described world, as the file stores it."""

    return {
        "Key": key,
        "tuple_ID": _TUPLE,
        "problemname": "Compl.trivial",
        "problemsize": 3,
        "text": _SETUP.format(x=x, y=y),
        "expectedresp": ["1", "2", "3"],
        "goldresp_obfusc": gold,
    }


#: The three trials of the file's first world, verbatim: their answers are "1", "2" and "3"
#: (obfuscated as Mark, Youssef, Yoda), so each option is right exactly once.
_TRIALS: list[dict[str, Any]] = [
    _trial(-276741083417243227, "history", "economics", "Mark"),
    _trial(2747235547611487721, "economics", "history", "Youssef"),
    _trial(2917042815647934077, "geography", "history", "Yoda"),
]

#: Every trial of the pinned file, by problem name and gold answer: each answer of a family is
#: right equally often (counted from the file, 2026-10-21).
_BALANCE: dict[str, dict[str, int]] = {
    "Compl.normal": {"1": 3348, "2": 3348, "3": 3348},
    "Compl.trivial": {"1": 3348, "2": 3348, "3": 3348},
    "Consist.normal": {"POSSIBLE": 10044, "IMPOSSIBLE": 10044},
    "Consist.trivial": {"POSSIBLE": 10044, "IMPOSSIBLE": 10044},
    "Infer.normal": {"TRUE": 10044, "FALSE": 10044},
    "Infer.trivial": {"TRUE": 3348, "FALSE": 3348},
}


def test_each_trial_of_a_world_is_its_own_case_named_by_its_key() -> None:
    """Three trials of one world, three answers, three ids: the dataset's own Key."""

    samples: list[Sample] = [record_to_sample(trial) for trial in _TRIALS]

    assert [sample.id for sample in samples] == [
        "worldsense_-276741083417243227",
        "worldsense_2747235547611487721",
        "worldsense_2917042815647934077",
    ]
    assert [sample.target for sample in samples] == ["1", "2", "3"]


def test_everything_but_the_id_is_inspect_evals_sample() -> None:
    """The question, options, key and metadata are inspect_evals' own, so the exam is theirs."""

    for trial in _TRIALS:
        ours: dict[str, Any] = record_to_sample(trial).model_dump(exclude={"id"})
        theirs: dict[str, Any] = inspect_evals_record_to_sample(trial).model_dump(exclude={"id"})
        assert ours == theirs


def test_tripwire_inspect_evals_names_every_trial_of_a_world_alike() -> None:
    """TRIPWIRE: v0.20.0 builds the id from the world, so its duplicate filter keeps one trial."""

    ids: set[str | int | None] = {inspect_evals_record_to_sample(trial).id for trial in _TRIALS}

    assert len(ids) == 1, (
        f"the pinned inspect_evals now names each WorldSense trial apart ({_PR}): point the "
        "worldsense row back at inspect_evals.worldsense.worldsense:worldsense and delete "
        "local_tasks/worldsense"
    )


@pytest.fixture(scope="module")
def ours() -> Dataset:
    """Every Sample the local Task serves, in file order (the row's shuffle=False)."""

    return worldsense(shuffle=False).dataset


def test_the_pinned_file_gives_every_trial_in_each_familys_balance(ours: Dataset) -> None:
    """87,048 Cases, one per trial, every gold answer of each family equally often."""

    balance: dict[str, Counter[str]] = {}
    for sample in ours:
        name: str = str((sample.metadata or {})["problemname"])
        balance.setdefault(name, Counter())[str(sample.target)] += 1

    assert len(ours) == 87048
    assert len({sample.id for sample in ours}) == 87048
    assert {name: dict(counts) for name, counts in balance.items()} == _BALANCE


def test_tripwire_inspect_evals_keeps_40176_trials_all_on_the_yes_side() -> None:
    """TRIPWIRE: v0.20.0's loader drops 46,872 trials and every FALSE, IMPOSSIBLE and "2"."""

    theirs: Dataset = load_worldsense_dataset(
        sample_fields=inspect_evals_record_to_sample, shuffle=False
    )

    assert len(theirs) == 40176, (
        f"the pinned inspect_evals now keeps every WorldSense trial ({_PR}): point the "
        "worldsense row back at inspect_evals.worldsense.worldsense:worldsense and delete "
        "local_tasks/worldsense"
    )
    assert {str(sample.target) for sample in theirs} == {"TRUE", "POSSIBLE", "1", "3"}


def test_the_row_serves_the_local_task_as_ours_with_the_evals_own_scorer() -> None:
    """Our code serves it, so the id drops `inspect-`; the eval's own scorer still grades."""

    spec = next(spec for spec in BENCHMARKS if spec.key == "worldsense")
    benchmark = imported_benchmark("worldsense")

    assert TASK_REPLAY_CASES["worldsense"].task == (
        "screamingface_engine_inspect.local_tasks.worldsense.worldsense:worldsense"
    )
    assert benchmark.benchmark.origin == "screamingface"
    assert benchmark.benchmark.case_count == 87048
    assert benchmark.benchmark.id == "worldsense"
    assert spec.scorer == "inspect_evals.worldsense.worldsense:pattern_with_metadata"
    assert benchmark.judge is None
