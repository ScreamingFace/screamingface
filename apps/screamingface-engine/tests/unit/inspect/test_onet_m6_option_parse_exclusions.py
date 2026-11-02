# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""O-NET M6: every question v0.20.0 builds wrongly is left out by id, and one the source garbles.

inspect_evals v0.20.0 splits a question's numbered options only at "N. " (number, dot,
space). The pinned dataset also writes "1.picnic" and "1 helpless", and has years inside
options, so some options are dropped, merged or split off. The answer letter comes from the
record's own number, so in those questions the sealed key can point at the wrong option's
text: 2021_40_e2b5's key is "careless" where the record's answer is "restless".
inspect_evals PR #2590 (open) parses the options in number order. The owner chose to leave
out every question where the two parses differ, rather than re-parse.

Separately, one question is wrong in the source data itself, so neither parser can fix it:
2020_32_08b1 gives options C and E the same text, and the key is C, so a reply of E names the
right answer and is marked wrong. It is left out by id too, under its own note.

What these tests pin, and why:

- the excluded ids are EXACTLY the questions whose prompt, options or key differ between
  v0.20.0's parse and #2590's, over the whole pinned file, each for the reason the row's
  comment gives (so a pin or parser change that moves one question fails here);
- 2021_40_e2b5 is excluded, and is the worked example: "careless" under v0.20.0, "restless"
  under #2590;
- the TRIPWIRE asserts inspect_evals v0.20.0 still keys 2021_40_e2b5 to "careless": when the
  inspect_evals pin reaches #2590 it fails and says all 24 parse exclusions can come back (the
  six from OME-1269 only with that decision owner's OK);
- 2020_32_08b1 is the only question both parses agree on whose key's text sits under two
  letters, and it is excluded;
- the row serves 397 less the 25 excluded ids.

The whole-file tests read the pinned Hub revision through inspect_evals' own `hf_dataset` call,
which downloads it once into the Hugging Face cache.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

import inspect_evals.onet.onet as inspect_evals_onet  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402

from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES  # noqa: E402

_PR: str = "https://github.com/UKGovernmentBEIS/inspect_evals/pull/2590"

#: How many questions inspect_evals' own filter keeps (answerable, single-answer choice).
_INSPECT_EVALS_QUESTIONS: int = 397

#: Why a question is left out: what v0.20.0's parse gets wrong next to #2590's.
_PAST_END: str = "key past the last option"
_WRONG_OPTION: str = "key names another option"
_OPTIONS_LOST: str = "options missing or merged, key right"

#: Every id excluded for a parse difference and its reason, as the row's comment in prepare.py
#: lists them. The first six were excluded first (OME-1269); the other 18 came with #2590.
_REASONS: dict[str, str] = {
    "2019_10ข_6985": _PAST_END,
    "2020_28_177b": _PAST_END,
    "2020_43_b673": _PAST_END,
    "2021_10_0325": _PAST_END,
    "2021_13_1922": _PAST_END,
    "2021_4_b447": _PAST_END,
    "2019_23_38bf": _WRONG_OPTION,
    "2019_27_0cda": _WRONG_OPTION,
    "2019_62_e6f7": _WRONG_OPTION,
    "2020_25_f98b": _WRONG_OPTION,
    "2020_30_aa8d": _WRONG_OPTION,
    "2021_17_309f": _WRONG_OPTION,
    "2021_17_b585": _WRONG_OPTION,
    "2021_22_d6cb": _WRONG_OPTION,
    "2021_29_b28c": _WRONG_OPTION,
    "2021_31_213c": _WRONG_OPTION,
    "2021_36_882c": _WRONG_OPTION,
    "2021_37_36fa": _WRONG_OPTION,
    "2021_38_60ca": _WRONG_OPTION,
    "2021_40_e2b5": _WRONG_OPTION,
    "2021_5ก_cd35": _WRONG_OPTION,
    "2021_60_3497": _WRONG_OPTION,
    "2019_10ก_6985": _OPTIONS_LOST,
    "2020_1ข_eead": _OPTIONS_LOST,
}

#: The one id excluded for a fault in the source data, not a parse: a separate Named Deviation.
#: Both parsers build it the same, with options C and E one text and the key C.
_DUPLICATE_OPTION: dict[str, str] = {"2020_32_08b1": "options C and E share the key's text"}

#: The real record behind 2021_40_e2b5, verbatim from matichon/thai-onet-m6-exam at the
#: pinned revision 93ffb5e3f3ec630b73e501937805984dd24f2365 (default config, test split).
#: Its first option is written "1 helpless" (no dot), which v0.20.0 does not see.
_RECORD_2021_40: dict[str, Any] = {
    "year": 2021,
    '"no"': '"40"',
    "instruction": (
        "1. Vocabulary (Item 36-40)\n    Directions: Choose the best alternative to complete "
        "each blank in the \n                       passage.\nTRAVELLING WITH CHILDREN: \n"
        "Tips, tricks and good ideas\nBREAKS\nTo avoid the monotony of long journeys, plan "
        "certain breaks along\nthe way before you set out. May be there's a _36_ area en "
        "route\nwhere you can stop for lunch, or a park which children will enjoy-\nit's an "
        "excellent way for them to use up _37_ energy.\nToys\nTake along a favorite teddy "
        "bear or doll to reassure and _38_ young\nor nervous children who are travelling for "
        "the first time.\nSURPRISES\nKeep a surprise lucky dip full of small, inexpensive "
        "gifts. It is a\nbrilliant way of cheering up or _39_ the children when their\n"
        "morale is low or they're feeling a bit _40_.\n\nWhat is the most suitable answer "
        "for _40_?"
    ),
    "input": "1 helpless\n2. hopeless\n3. tireless\n4. restless\n5. careless",
    "result": "4. restless",
    "isAnswerable": True,
    "isMultipleChoice": True,
    "isSingleChoiceSolution": True,
}


def _split_in_number_order(text: str) -> tuple[str, list[str]]:
    """Find option 1, then option 2 after it, and so on, so a number inside an option is never
    taken for the next one.

    A faithful copy of `split_numbered_list` from inspect_evals PR #2590 at its head commit,
    annotations added (MIT, Arthit Suriyawongkul and contributors):
    https://github.com/UKGovernmentBEIS/inspect_evals/blob/3778bdff7c1b77aba2063d14ab84b8daf4ed1873/src/inspect_evals/onet/onet.py
    It is the reference parse here only; no Case is built with it.
    """

    markers: list[re.Match[str]] = []
    number: int = 1
    while True:
        marker: re.Match[str] | None = re.compile(
            rf"^{number}(?!\d)\s*\.?\s*|(?<=\s){number}\.\s+", re.MULTILINE
        ).search(text, markers[-1].end() if markers else 0)
        if marker is None:
            break
        markers.append(marker)
        number += 1

    if not markers:
        return text.strip(), []

    lead_text: str = text[: markers[0].start()].strip()
    ends: list[int] = [m.start() for m in markers[1:]] + [len(text)]
    numbered_list: list[str] = [
        text[marker.end() : end].strip() for marker, end in zip(markers, ends, strict=True)
    ]
    return lead_text, numbered_list


def _key_text(sample: Sample) -> str | None:
    """The option text the sealed answer letter selects; None when it points past the end."""

    index: int = ord(str(sample.target)) - ord("A")
    choices: list[str] = list(sample.choices or [])
    return choices[index] if index < len(choices) else None


def _reason(v0_20: Sample, number_order: Sample) -> str | None:
    """Why one question differs between the two parses; None when they build it the same."""

    if (v0_20.input, v0_20.choices, v0_20.target) == (
        number_order.input,
        number_order.choices,
        number_order.target,
    ):
        return None
    if _key_text(v0_20) is None:
        return _PAST_END
    return _WRONG_OPTION if _key_text(v0_20) != _key_text(number_order) else _OPTIONS_LOST


@pytest.fixture(scope="module")
def both_parses() -> Iterator[tuple[dict[str, Sample], dict[str, Sample]]]:
    """inspect_evals' own Task over the pinned file, once as v0.20.0 parses it and once with
    #2590's parse swapped in; each keyed by Sample id (the id hashes the question alone)."""

    v0_20: dict[str, Sample] = {
        str(sample.id): sample for sample in inspect_evals_onet.onet_m6(shuffle=False).dataset
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(inspect_evals_onet, "split_numbered_list", _split_in_number_order)
        number_order: dict[str, Sample] = {
            str(sample.id): sample for sample in inspect_evals_onet.onet_m6(shuffle=False).dataset
        }
    yield v0_20, number_order


def test_the_excluded_ids_are_exactly_where_the_two_parses_differ(
    both_parses: tuple[dict[str, Sample], dict[str, Sample]],
) -> None:
    """Every question #2590 builds differently is left out, each for its stated reason, and
    no question both parses agree on is, apart from the one named duplicate-option id."""

    v0_20, number_order = both_parses
    differing: dict[str, str] = {}
    for sample_id, sample in v0_20.items():
        reason: str | None = _reason(sample, number_order[sample_id])
        if reason is not None:
            differing[sample_id] = reason
    excluded: tuple[str, ...] | None = TASK_REPLAY_CASES["onet_m6"].excluded_sample_ids

    assert set(v0_20) == set(number_order)
    assert len(v0_20) == _INSPECT_EVALS_QUESTIONS
    assert differing == _REASONS
    assert excluded is not None and sorted(excluded) == sorted({**_REASONS, **_DUPLICATE_OPTION})


def test_2020_32_08b1_is_the_one_agreed_question_whose_key_text_sits_under_two_letters(
    both_parses: tuple[dict[str, Sample], dict[str, Sample]],
) -> None:
    """A source-data fault neither parser catches: a reply naming the right text under the
    other letter would be marked wrong, so the question is left out by id."""

    v0_20, number_order = both_parses
    duplicated: set[str] = set()
    for sample_id, sample in v0_20.items():
        if sample_id in _REASONS:
            continue  # parse faults, excluded above
        key: str | None = _key_text(sample)
        assert sample.choices == number_order[sample_id].choices
        if key is not None and list(sample.choices or []).count(key) > 1:
            duplicated.add(sample_id)
    excluded: tuple[str, ...] | None = TASK_REPLAY_CASES["onet_m6"].excluded_sample_ids
    choices: list[str] = list(v0_20["2020_32_08b1"].choices or [])

    assert duplicated == set(_DUPLICATE_OPTION)
    assert v0_20["2020_32_08b1"].target == "C"
    assert choices[2] == choices[4] == "สนับสนุน สรุป สนับสนุน"
    assert excluded is not None and "2020_32_08b1" in excluded


def test_2021_40_e2b5_is_excluded_because_its_key_names_another_option(
    both_parses: tuple[dict[str, Sample], dict[str, Sample]],
) -> None:
    """The worked example: v0.20.0 drops "1 helpless", so letter D lands on "careless"."""

    v0_20, number_order = both_parses
    excluded: tuple[str, ...] | None = TASK_REPLAY_CASES["onet_m6"].excluded_sample_ids

    assert excluded is not None and "2021_40_e2b5" in excluded
    assert _REASONS["2021_40_e2b5"] == _WRONG_OPTION
    assert v0_20["2021_40_e2b5"].target == number_order["2021_40_e2b5"].target == "D"
    assert _key_text(v0_20["2021_40_e2b5"]) == "careless"
    assert _key_text(number_order["2021_40_e2b5"]) == "restless"


def test_tripwire_inspect_evals_still_keys_2021_40_e2b5_to_careless() -> None:
    """TRIPWIRE: v0.20.0's parser still selects the wrong option for the real record."""

    sample: Sample = inspect_evals_onet.record_to_sample(_RECORD_2021_40)

    assert sample.id == "2021_40_e2b5"
    assert _key_text(sample) == "careless", (
        f"the pinned inspect_evals now parses O-NET options in number order ({_PR}), which "
        "builds all 24 parse exclusions in onet_m6's excluded_sample_ids right: the 18 the "
        "#2590 Named Deviation added can come back now, and the six from OME-1269 need that "
        "decision owner's OK first. 2020_32_08b1 stays out (a source-data fault, not a parse). "
        "Re-seal the row and delete this file's #2590 tests"
    )


def test_the_number_order_parse_keys_2021_40_e2b5_to_the_records_answer() -> None:
    """The reference parse reads all five options, so D is "restless", the record's answer."""

    lead_text, options = _split_in_number_order(str(_RECORD_2021_40["input"]))

    assert lead_text == ""
    assert options == ["helpless", "hopeless", "tireless", "restless", "careless"]
    assert options[3] == str(_RECORD_2021_40["result"]).removeprefix("4. ")


def test_the_row_serves_inspect_evals_questions_less_the_excluded() -> None:
    """397 kept by inspect_evals' filter, less the 24 parse exclusions and the 1 duplicate-option
    question: 372 Cases."""

    row = TASK_REPLAY_CASES["onet_m6"]
    left_out: int = len(_REASONS) + len(_DUPLICATE_OPTION)

    assert row.excluded_sample_ids is not None
    assert len(set(row.excluded_sample_ids)) == len(row.excluded_sample_ids) == left_out
    assert row.case_count == _INSPECT_EVALS_QUESTIONS - left_out == 372
    assert imported_benchmark("onet_m6").benchmark.case_count == 372
