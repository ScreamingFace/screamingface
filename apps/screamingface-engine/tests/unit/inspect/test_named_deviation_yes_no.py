# pyright: reportMissingImports=false
# WHY file-level: the scorers import inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""PAWS and BoolQ graded on a bare Yes or No: inspect_evals PR #2334, adopted as our own.

What these tests pin, and why:

- a bare Yes or No, wrapped only in spaces or punctuation, is graded against the key;
- the non-answers v0.20.0 passes are wrong under ours, and the TRIPWIRE asserts v0.20.0 still
  passes them: when the pin reaches the fix, it fails and says to point the rows back at the
  eval's own scorer (https://github.com/UKGovernmentBEIS/inspect_evals/pull/2334);
- the rows grade with these scorers.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Scorer, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.named_deviations.yes_no.yes_no import (  # noqa: E402
    boolq_yes_no,
    paws_yes_no,
)

_OURS: dict[str, Scorer] = {"paws": paws_yes_no(), "boolq": boolq_yes_no()}


def _inspect_evals_scorer(row: str, monkeypatch: pytest.MonkeyPatch) -> Scorer:
    """The scorer inspect_evals' own Task declares at the pinned version, built with no Hub."""

    # WHY import_module: each package re-exports its Task function under the module's own name,
    # so `inspect_evals.paws.paws` as an attribute is the function, not the module.
    module: Any = import_module(f"inspect_evals.{row}.{row}")
    stand_in = MemoryDataset([Sample(input="q", target="No")])
    monkeypatch.setattr(module, "hf_dataset", lambda **_kwargs: stand_in)
    return list(getattr(module, row)().scorer or [])[0]


async def _graded(scorer: Scorer, reply: str, key: str) -> object:
    """The grade one scorer gives one reply against one key."""

    state = TaskState(
        model="none/none",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="q",
        messages=[],
        output=ModelOutput.from_content(model="none/none", content=reply),
    )
    score = await scorer(state, Target(key))
    assert score is not None
    return score.value


@pytest.mark.asyncio
@pytest.mark.parametrize("row", ["paws", "boolq"])
@pytest.mark.parametrize(
    ("reply", "key", "grade"),
    [
        ("No", "No", CORRECT),
        ("yes", "Yes", CORRECT),
        ("**No.**", "No", CORRECT),
        ("Yes", "No", INCORRECT),
    ],
)
async def test_a_bare_yes_or_no_is_graded_against_the_key(
    row: str, reply: str, key: str, grade: str
) -> None:
    assert await _graded(_OURS[row], reply, key) == grade


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "reply"),
    [
        # PAWS: includes() finds "no" inside "cannot" and "know" (4,464 of the 8,000 keys are No).
        ("paws", "I cannot determine this."),
        ("paws", "I don't know"),
        ("paws", "yesno"),
        # BoolQ: the reply ends in "no" plus one character (all 1,237 No keys).
        ("boolq", "I don't know"),
        ("boolq", "Domino"),
    ],
)
async def test_tripwire_a_non_answer_inspect_evals_passes_is_wrong_under_ours(
    row: str, reply: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRIPWIRE (inspect_evals PR #2334): the first assert is the verdict of the scorer
    inspect_evals' Task declares; when a pin bump makes it fail, inspect_evals has the fix and
    this row's Named Deviation can go."""

    assert await _graded(_inspect_evals_scorer(row, monkeypatch), reply, "No") == CORRECT
    assert await _graded(_OURS[row], reply, "No") == INCORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize("row", ["paws", "boolq"])
async def test_a_label_wrapped_in_prose_is_wrong_as_inspect_evals_decided(
    row: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the trade: the prompts ask for the bare word, and inspect_evals' fix
    marks "The answer is: No" as no answer. v0.20.0 passed it."""

    assert (
        await _graded(_inspect_evals_scorer(row, monkeypatch), "The answer is: No", "No") == CORRECT
    )
    assert await _graded(_OURS[row], "The answer is: No", "No") == INCORRECT


def test_the_rows_grade_with_the_bare_yes_no_scorers() -> None:
    scorers: dict[str, str] = {spec.key: spec.scorer for spec in BENCHMARKS}

    assert scorers["paws"].endswith("named_deviations.yes_no.yes_no:paws_yes_no")
    assert scorers["boolq"].endswith("named_deviations.yes_no.yes_no:boolq_yes_no")
