"""A scorer that is our code joins the Benchmark revision by its source.

What these tests pin, and why: an Imported Benchmark's revision names its Task and its Case
Digest, and leans on the `inspect-ai` / `inspect-evals` version pins for the grading code. A
row that grades with OUR scorer instead (a Named Deviation adopting an inspect_evals fix) has
no such pin, so without this rule an edit to that scorer would change scores under a published
revision with no test failing. A local Task's own scorers already ride its `task_source` pin.

Runs without the `inspect` extra: the rule locates modules, it never imports them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine_inspect.benchmarks import BENCHMARKS
from screamingface_engine_inspect.local_tasks import scorer_source_pins, source_digest
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES

#: The rows whose scorer is ours but not their Task's (OME-1701 PR 1).
_DEVIATING_ROWS: frozenset[str] = frozenset({"paws", "boolq"})


def _stand_in_scorer_package(root: Path, name: str) -> Path:
    """A one-module scorer package on disk, standing in for one of ours."""

    package: Path = root / name
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "scorers.py").write_text("def headline():\n    return None\n")
    return package


def test_our_scorer_beside_an_inspect_evals_task_is_pinned_by_its_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package: Path = _stand_in_scorer_package(tmp_path, "stand_in_deviation")
    monkeypatch.syspath_prepend(str(tmp_path))

    pins: tuple[str, ...] = scorer_source_pins(
        "inspect_evals.paws.paws:paws", ("stand_in_deviation.scorers:headline",)
    )

    assert pins == (f"scorer_source={source_digest(package)}",)


def test_an_edit_to_that_scorer_moves_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: the grading rule is Benchmark identity; one byte of it is a new revision."""

    package: Path = _stand_in_scorer_package(tmp_path, "stand_in_edited")
    monkeypatch.syspath_prepend(str(tmp_path))
    reference: tuple[str, ...] = ("stand_in_edited.scorers:headline",)
    before: tuple[str, ...] = scorer_source_pins("inspect_evals.paws.paws:paws", reference)

    (package / "scorers.py").write_text("def headline():\n    return 1\n")

    assert scorer_source_pins("inspect_evals.paws.paws:paws", reference) != before


def test_inspects_scorers_and_a_local_tasks_own_scorers_are_not_pinned_again() -> None:
    """inspect's and inspect_evals' scorers ride the package version pins; a local Task's
    scorers sit in the package its `task_source` pin already hashes."""

    assert scorer_source_pins("inspect_evals.paws.paws:paws", ("inspect_ai.scorer:includes",)) == ()
    assert (
        scorer_source_pins(
            "inspect_evals.chembench.chembench:chembench",
            ("inspect_evals.chembench.chembench:chembench_scorer",),
        )
        == ()
    )
    assert (
        scorer_source_pins(
            "screamingface_engine_inspect.local_tasks.bbh.bbh:bbh",
            ("screamingface_engine_inspect.local_tasks.bbh.bbh:bbh_scorer",),
        )
        == ()
    )


def test_two_scorers_from_one_package_give_one_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MATH's headline and its Named Score come from one package: one digest covers both."""

    _stand_in_scorer_package(tmp_path, "stand_in_pair")
    monkeypatch.syspath_prepend(str(tmp_path))

    pins: tuple[str, ...] = scorer_source_pins(
        "inspect_evals.math.math:math",
        ("stand_in_pair.scorers:headline", "stand_in_pair.scorers:headline"),
    )

    assert len(pins) == 1


def test_a_scorer_that_cannot_be_located_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be located"):
        scorer_source_pins("inspect_evals.paws.paws:paws", ("no_such_package.scorers:headline",))


def test_only_the_rows_grading_with_our_scorer_beside_an_inspect_evals_task_carry_the_pin() -> None:
    """INVARIANT: the rule moves no other published revision; every other row's scorer is
    inspect's, inspect_evals' or its own local Task's."""

    pinned: set[str] = {
        spec.key
        for spec in BENCHMARKS
        if scorer_source_pins(TASK_REPLAY_CASES[spec.key].task, (spec.scorer, *spec.extra_scorers))
    }

    assert pinned == _DEVIATING_ROWS
