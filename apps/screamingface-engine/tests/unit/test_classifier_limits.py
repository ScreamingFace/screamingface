"""The strict C7 reader of a classifier row's `input_contracts` and `limits` (Unit 5.2).

FEATURE: Router Recipe extension. The dynamic named-profile preflight and the Engine classifier
catalog (C17) read the Gateway's classifier metadata through one strict reader: an invalid row is
unusable, never repaired, and nothing is inferred from a model ID.

INVARIANT: a choice input fits only a classifier that declares `choice` and valid, non-null
`ChoiceLimits` at least as large as every count and length of that input.
"""

from __future__ import annotations

from typing import Any

import pytest

from screamingface_engine.world.classifier_limits import (
    ChoiceRequest,
    choice_fits,
    read_capability,
)

_TEXT = {
    "contract": "classifier-limits-v1",
    "max_labels": 32,
    "max_label_bytes": 64,
    "max_text_chars": 20000,
}
_CHOICE = {
    **_TEXT,
    "max_options": 3,
    "max_description_chars": 20,
    "max_instructions_chars": 30,
}


def _choice(**changes: Any) -> dict[str, Any]:
    return {**_CHOICE, **changes}


# --- reading a row --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("contracts", "limits"),
    [
        (["text"], None),
        (["text"], _TEXT),
        (["choice"], _CHOICE),
        (["text", "choice"], _CHOICE),
    ],
)
def test_every_valid_c7_row_reads(contracts: list[str], limits: object) -> None:
    capability = read_capability(contracts, limits)

    assert capability is not None
    assert capability.input_contracts == tuple(contracts)
    assert capability.projection() == {"input_contracts": contracts, "limits": limits}


@pytest.mark.parametrize(
    ("contracts", "limits"),
    [
        pytest.param(["choice"], None, id="choice-null"),
        pytest.param(["choice"], _TEXT, id="choice-text-limits"),
        pytest.param(["text"], _CHOICE, id="text-choice-limits"),
        pytest.param(["choice", "text"], _CHOICE, id="reversed"),
        pytest.param(["text", "text"], _TEXT, id="repeated"),
        pytest.param([], None, id="empty"),
        pytest.param(["vision"], None, id="unknown"),
        pytest.param("text", None, id="string"),
        pytest.param(None, None, id="absent"),
        pytest.param(["choice"], _choice(contract="classifier-limits-v2"), id="contract"),
        pytest.param(["choice"], {k: v for k, v in _CHOICE.items() if k != "contract"}, id="no-ct"),
        pytest.param(["choice"], _choice(max_tokens=4), id="extra-key"),
        pytest.param(["choice"], _choice(max_options=True), id="bool"),
        pytest.param(["choice"], _choice(max_options=3.0), id="float"),
        pytest.param(["choice"], _choice(max_options=0), id="zero"),
        pytest.param(["choice"], _choice(max_options=2147483648), id="over"),
        pytest.param(["choice"], _choice(max_options="3"), id="string-value"),
        pytest.param(["choice"], [], id="list"),
    ],
)
def test_an_invalid_row_is_unusable(contracts: object, limits: object) -> None:
    assert read_capability(contracts, limits) is None


def test_both_bounds_of_a_limit_read() -> None:
    assert read_capability(["choice"], _choice(max_options=1, max_labels=2147483647)) is not None


# --- does a choice input fit ----------------------------------------------------------------------


def _request(**changes: Any) -> ChoiceRequest:
    fields: dict[str, Any] = {
        "labels": ("code", "general", "math"),
        "descriptions": ("d" * 20, "e", "f"),
        "instructions": "i" * 30,
        "text": "t" * 20000,
    }
    fields.update(changes)
    return ChoiceRequest(**fields)


def test_an_input_at_every_limit_fits() -> None:
    capability = read_capability(["choice"], _choice(max_label_bytes=7))

    assert capability is not None
    assert choice_fits(capability, _request(labels=("é" * 3 + "x", "general", "math")))


@pytest.mark.parametrize(
    ("limits", "request_changes"),
    [
        pytest.param({"max_options": 2}, {}, id="options"),
        pytest.param({"max_labels": 2}, {}, id="labels"),
        pytest.param({"max_label_bytes": 6}, {"labels": ("ééé", "general", "math")}, id="bytes"),
        pytest.param({}, {"descriptions": ("d" * 21, "e", "f")}, id="description"),
        pytest.param({}, {"instructions": "i" * 31}, id="instructions"),
        pytest.param({}, {"text": "t" * 20001}, id="text"),
    ],
)
def test_an_input_over_one_limit_does_not_fit(
    limits: dict[str, int], request_changes: dict[str, Any]
) -> None:
    capability = read_capability(["choice"], _choice(**limits))

    assert capability is not None
    assert not choice_fits(capability, _request(**request_changes))


@pytest.mark.parametrize(
    ("contracts", "limits"), [(["text"], None), (["text"], _TEXT)], ids=["null", "text"]
)
def test_a_text_only_classifier_takes_no_choice(contracts: list[str], limits: object) -> None:
    capability = read_capability(contracts, limits)

    assert capability is not None
    assert not choice_fits(capability, _request())


def test_the_text_length_counts_code_points() -> None:
    capability = read_capability(["choice"], _choice(max_text_chars=3))

    assert capability is not None
    assert choice_fits(capability, _request(text="😀😀😀"))
    assert not choice_fits(capability, _request(text="😀😀😀😀"))
