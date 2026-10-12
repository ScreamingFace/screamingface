# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Case Preparation accepts a list of accepted answers as the Case's target (OME-1268, PR 4).

FEATURE: SQuAD's answer key is a list of strings (every accepted span); inspect's own f1 and
exact take the best match over such a list. The Grading Material freezes the list as the
scorer reads it, so the grading code is untouched.

INVARIANT: a string target prepares exactly as before; an empty list, a list with a blank or
non-string entry, and a list beside multiple-choice options are still refused by name. The
one exception is a row that says some Cases' empty key is their answer (OME-1527 R5): there
an empty key is frozen as the Sample held it, and every non-empty key is checked as before.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import CORRECT, Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PrepareError,
    prepared_case,
)
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402


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


# --- OME-1527 R5: a row whose empty keys are answers (contracteval's "no related clause") ---


def _allowing_case(target: Any, choices: list[str] | None = None) -> dict[str, Any]:
    """Prepare one Case under a row that says some Cases' empty key is their answer."""

    spec = replace(TASK_REPLAY_CASES["gsm8k"], empty_answer_key_allowed=True)
    sample = Sample(input="Quote the non-compete clause.", target=target, choices=choices)
    return prepared_case(sample, 1, "Quote the non-compete clause.", spec)


@pytest.mark.parametrize("empty", [[], ""])
def test_an_empty_key_is_accepted_only_on_a_row_that_allows_it(empty: Any) -> None:
    """The trust boundary still refuses an unkeyed Case by default; only the row's opt-in
    turns an empty key into a fact, frozen in the shape the Sample held it."""

    with pytest.raises(PrepareError, match="target is empty"):
        _case(empty)

    assert _allowing_case(empty)["grading_material"] == {"target": empty}


@pytest.mark.parametrize(
    ("bad", "reason"),
    [(["Section 4.2", ""], "accepted answers"), ("   ", "target is empty")],
)
def test_a_row_allowing_empty_keys_still_validates_every_non_empty_key(
    bad: Any, reason: str
) -> None:
    """The opt-in covers emptiness only: a blank span inside a key, or a whitespace key, is
    still a broken Sample, refused by name."""

    with pytest.raises(PrepareError, match=reason):
        _allowing_case(bad)


def test_a_row_allowing_empty_keys_still_refuses_an_empty_key_beside_choices() -> None:
    # A multiple-choice Case with no key names no option; the opt-in is for free text only.
    with pytest.raises(PrepareError, match="target is empty"):
        _allowing_case("", choices=["one", "two"])


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_target", [[], "", ["laws of Delaware"]])
async def test_the_scorer_gets_back_the_key_inspect_would_have_given_it(
    sample_target: Any,
) -> None:
    """INVARIANT: after the Grading Material's JSON round trip, the eval's own scorer sees the
    Target inspect builds from the Sample itself. WHY it matters for []: Target([]) holds no
    answers, Target("") holds one blank one; freezing [] as "" would let an all-of scorer
    find that blank in every reply and mark a missed clause correct."""

    seen: list[list[str]] = []

    async def recording(state: TaskState, target: Target) -> Score:
        seen.append(list(target))
        return Score(value=CORRECT)

    material: object = json.loads(json.dumps(_allowing_case(sample_target)["grading_material"]))
    request: GradeRequest = GradeRequest(
        case_id=1,
        input=TextPayload(text="Quote the non-compete clause."),
        answer=TextPayload(text="There is no related clause."),
        row={"case": {"status": "answered"}},
        material=material,
    )
    await inspect_grade_case(recording)(request)

    assert seen == [list(Target(sample_target))]
