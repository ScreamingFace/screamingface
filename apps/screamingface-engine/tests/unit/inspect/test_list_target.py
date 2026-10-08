# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Case Preparation accepts a list of accepted answers as the Case's target (OME-1268, PR 4).

FEATURE: SQuAD's answer key is a list of strings (every accepted span); inspect's own f1 and
exact take the best match over such a list. The Grading Material freezes the list as the
scorer reads it, so the grading code is untouched.

INVARIANT: a string target prepares exactly as before; an empty list, a list with a blank or
non-string entry, and a list beside multiple-choice options are still refused by name.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.dataset import Sample  # noqa: E402

from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PrepareError,
    prepared_case,
)


def _case(target: Any, choices: list[str] | None = None) -> dict[str, Any]:
    spec = replace(TASK_REPLAY_CASES["gsm8k"])
    sample = Sample(input="When was the Eiffel Tower built?", target=target, choices=choices)
    return prepared_case(sample, 1, "When was the Eiffel Tower built?", spec)


def test_a_list_of_accepted_answers_is_frozen_as_a_list() -> None:
    prepared = _case(["1889", "1887–1889"])

    assert prepared["grading_material"] == {"target": ["1889", "1887–1889"]}
    assert prepared["case"]["id"] == 1


def test_a_string_target_prepares_exactly_as_before() -> None:
    assert _case("42")["grading_material"] == {"target": "42"}


def test_an_empty_list_target_is_refused_by_name() -> None:
    with pytest.raises(PrepareError, match="target is empty"):
        _case([])


@pytest.mark.parametrize("bad", [["1889", ""], ["   "]])
def test_a_list_with_a_blank_entry_is_refused_by_name(bad: list[Any]) -> None:
    with pytest.raises(PrepareError, match="accepted answers"):
        _case(bad)


def test_a_list_target_beside_choices_is_refused() -> None:
    # A list key over multiple-choice options is a multi-answer MCQ, which no row declares.
    with pytest.raises(PrepareError, match="choices"):
        _case(["A", "C"], choices=["one", "two", "three"])
