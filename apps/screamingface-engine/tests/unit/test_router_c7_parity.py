"""The Engine reads C7 labels and limits as the Gateway does.

FEATURE: Router Recipe extension (contracts C2, C5, C7, C17; Unit 5.2). A label the Gateway
refuses never reaches a provider from the Engine either, and a classifier row the Gateway could
never publish is unusable here.

INVARIANT: a label is 1-64 UTF-8 bytes with no character of any Unicode `C` category (control,
format, surrogate, private use, unassigned): the Gateway's classification-input label rule in
full. The category part alone is also the SDK's rule for recipe names, which have no byte bound.
INVARIANT: a choice row holds the C7 choice ranges, `max_options <= max_labels <= 32`; a text row
holds its three keys in `1..2147483647`.
WHY data and no import of the Gateway or the SDK: the Engine depends on neither, so these vectors
restate the contract here.
"""

from __future__ import annotations

import unicodedata
from typing import Any

import pytest
from classifier_catalog_support import json_answer, listed_rows, listing, projected, row
from pydantic import ValidationError
from router_support import choice_definition, spec_text

from screamingface_engine.router_vocabulary import ScoreRow, SelectorRecord
from screamingface_engine.world.classifier_limits import read_capability
from screamingface_engine.world.router_spec import RouterSpecError, parse_router_spec

# --- labels -----------------------------------------------------------------------------------

_REFUSED_LABELS = [
    pytest.param("a\u200bb", "Cf", id="format-zero-width-space"),
    pytest.param("\ue000", "Co", id="private-use"),
    pytest.param("a\u0378", "Cn", id="unassigned"),
    pytest.param("a\u0007", "Cc", id="control"),
]
_LONE_SURROGATE = "a\ud800"
"""Category `Cs`; a JSON text holding it is not valid Unicode, so C2 refuses it at the root."""
_ACCEPTED_LABELS = [
    pytest.param("a\u00a0b", id="no-break-space-is-not-C"),
    pytest.param("\u00e9" * 32, id="exactly-64-utf8-bytes"),
    pytest.param("x", id="one-character"),
]


_LABEL_PATH = r"candidates\.0\.described\.label \(a label is 1-64 UTF-8 bytes"


def _labelled(label: str) -> dict[str, Any]:
    """A valid choice Router whose first candidate is ``label``."""
    definition = choice_definition()
    definition["candidates"][0]["label"] = label
    return definition


@pytest.mark.parametrize(("label", "category"), _REFUSED_LABELS)
def test_a_definition_label_of_any_c_category_is_refused(label: str, category: str) -> None:
    assert {unicodedata.category(char) for char in label} & {category} == {category}

    with pytest.raises(RouterSpecError, match=_LABEL_PATH):
        parse_router_spec(spec_text(_labelled(label)))


def test_a_definition_label_with_a_lone_surrogate_is_refused() -> None:
    with pytest.raises(RouterSpecError):
        parse_router_spec(spec_text(_labelled(_LONE_SURROGATE)))


@pytest.mark.parametrize("label", _ACCEPTED_LABELS)
def test_a_definition_label_with_no_c_category_is_accepted(label: str) -> None:
    spec = parse_router_spec(spec_text(_labelled(label)))

    assert spec.definition.candidates[0].label == label


def test_a_label_over_64_utf8_bytes_is_refused() -> None:
    with pytest.raises(RouterSpecError, match=_LABEL_PATH):
        parse_router_spec(spec_text(_labelled("\u00e9" * 32 + "x")))


def _selector(label: str) -> SelectorRecord:
    return SelectorRecord.model_validate(
        {"source": "llm", "labels": (label,), "unknown": (), "parse": "ok"}
    )


@pytest.mark.parametrize(
    "label", [*(param.values[0] for param in _REFUSED_LABELS), _LONE_SURROGATE]
)
def test_a_record_label_of_any_c_category_is_refused(label: str) -> None:
    # INVARIANT (C5): a returned label the Gateway would refuse never stands in a record.
    with pytest.raises(ValidationError, match="a label is 1-64 UTF-8 bytes"):
        _selector(label)
    with pytest.raises(ValidationError, match="a label is 1-64 UTF-8 bytes"):
        ScoreRow.model_validate({"label": label, "score": 0.5})


@pytest.mark.parametrize("label", _ACCEPTED_LABELS)
def test_a_record_label_with_no_c_category_is_accepted(label: str) -> None:
    assert _selector(label).labels == (label,)


# --- limits -----------------------------------------------------------------------------------

_MAX = 2147483647
_CHOICE_MAXIMA = {
    "contract": "classifier-limits-v1",
    "max_labels": 32,
    "max_label_bytes": 64,
    "max_text_chars": _MAX,
    "max_options": 32,
    "max_description_chars": 1024,
    "max_instructions_chars": 4096,
}
_CHOICE_MINIMA = {key: (value if key == "contract" else 1) for key, value in _CHOICE_MAXIMA.items()}
_TEXT_MAXIMA = {
    "contract": "classifier-limits-v1",
    "max_labels": _MAX,
    "max_label_bytes": _MAX,
    "max_text_chars": _MAX,
}


def _choice(**changes: int) -> dict[str, Any]:
    return {**_CHOICE_MAXIMA, **changes}


@pytest.mark.parametrize(
    "limits",
    [
        pytest.param(_CHOICE_MAXIMA, id="every-choice-maximum"),
        pytest.param(_CHOICE_MINIMA, id="every-minimum"),
        pytest.param(_choice(max_options=5, max_labels=5), id="labels-equal-options"),
    ],
)
@pytest.mark.parametrize("contracts", [["choice"], ["text", "choice"]])
def test_a_choice_row_within_the_c7_ranges_is_usable(
    contracts: list[str], limits: dict[str, Any]
) -> None:
    assert read_capability(contracts, limits) is not None


@pytest.mark.parametrize(
    "limits",
    [
        pytest.param(_choice(max_options=33, max_labels=32), id="max_options-33"),
        pytest.param(_choice(max_labels=33), id="max_labels-33"),
        pytest.param(_choice(max_labels=_MAX), id="max_labels-int-max"),
        pytest.param(_choice(max_label_bytes=65), id="max_label_bytes-65"),
        pytest.param(_choice(max_description_chars=1025), id="max_description_chars-1025"),
        pytest.param(_choice(max_instructions_chars=4097), id="max_instructions_chars-4097"),
        pytest.param(_choice(max_text_chars=_MAX + 1), id="max_text_chars-past-int-max"),
        pytest.param(_choice(max_options=3, max_labels=2), id="fewer-labels-than-options"),
        pytest.param(
            {key: _MAX if key != "contract" else value for key, value in _CHOICE_MAXIMA.items()},
            id="every-key-int-max",
        ),
    ],
)
@pytest.mark.parametrize("contracts", [["choice"], ["text", "choice"]])
def test_a_choice_row_outside_the_c7_ranges_is_unusable(
    contracts: list[str], limits: dict[str, Any]
) -> None:
    assert read_capability(contracts, limits) is None


def test_a_text_row_keeps_its_three_keys_up_to_int_max() -> None:
    assert read_capability(["text"], _TEXT_MAXIMA) is not None
    assert read_capability(["text"], {**_TEXT_MAXIMA, "max_labels": _MAX + 1}) is None
    assert read_capability(["text"], {**_TEXT_MAXIMA, "max_labels": 0}) is None


@pytest.mark.asyncio
async def test_the_catalog_omits_a_choice_row_the_gateway_could_not_publish() -> None:
    usable = row("byom_a/choice", ["choice"], _CHOICE_MAXIMA)
    too_wide = row("byom_a/wide", ["choice"], _choice(max_labels=33))
    inverted = row("byom_a/inverted", ["choice"], _choice(max_options=3, max_labels=2))

    rows = await listed_rows(json_answer(200, listing(too_wide, usable, inverted)))

    assert rows == [projected(usable)]
