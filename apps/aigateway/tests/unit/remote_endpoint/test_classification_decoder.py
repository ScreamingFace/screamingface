"""The one decoder of a classifier's HTTP 200 answer, for both configured envelopes.

# FEATURE: hosted BYOM Unit 3 — `flat` is a list of `{label, score}`; `single-batch` is a list
# holding exactly one such list. Nothing else is flattened, picked, sorted or dropped.
# INVARIANT: at least one item; labels are nonempty unique strings; scores are finite numbers,
# not booleans, within [0, 1]. The sum is not checked.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aigateway.plugins.remote_endpoint.classification import decode_scores

from .fixtures import JSON_TYPE

TIED = [
    {"label": "b", "score": 0.25},
    {"label": "a", "score": 0.5},
    {"label": "c", "score": 0.25},
]


def _decode(value: Any, envelope: str, content_type: str | None = JSON_TYPE) -> Any:
    return decode_scores(content_type, json.dumps(value).encode(), envelope=envelope)


@pytest.mark.parametrize("envelope, value", [("flat", TIED), ("single-batch", [TIED])])
def test_both_envelopes_decode_in_upstream_order_with_ties_kept(envelope: str, value: Any) -> None:
    assert _decode(value, envelope) == TIED


def test_scores_at_both_bounds_and_integers_are_scores() -> None:
    scores = [
        {"label": "low", "score": 0},
        {"label": "high", "score": 1},
        {"label": "x", "score": 1.0},
    ]

    assert _decode(scores, "flat") == scores


def test_the_sum_is_not_checked() -> None:
    scores = [{"label": "a", "score": 0.9}, {"label": "b", "score": 0.9}]

    assert _decode(scores, "flat") == scores


def test_only_the_label_and_the_score_of_an_item_are_kept() -> None:
    scored = [{"label": "a", "score": 0.5, "index": 3}]

    assert _decode(scored, "flat") == [{"label": "a", "score": 0.5}]


def _with(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"label": "ok", "score": 0.5}, item]


REFUSED: dict[str, Any] = {
    "empty-list": [],
    "duplicate-label": _with({"label": "ok", "score": 0.1}),
    "empty-label": _with({"label": "", "score": 0.1}),
    "number-label": _with({"label": 7, "score": 0.1}),
    "null-label": _with({"label": None, "score": 0.1}),
    "missing-label": _with({"score": 0.1}),
    "boolean-score": _with({"label": "b", "score": True}),
    "string-score": _with({"label": "b", "score": "0.1"}),
    "missing-score": _with({"label": "b"}),
    "negative-score": _with({"label": "b", "score": -0.01}),
    "score-above-one": _with({"label": "b", "score": 1.01}),
    "item-not-an-object": ["label"],
    "object-not-a-list": {"label": "a", "score": 0.5},
}


@pytest.mark.parametrize("envelope", ["flat", "single-batch"])
@pytest.mark.parametrize("value", REFUSED.values(), ids=REFUSED.keys())
def test_a_malformed_score_list_is_refused(envelope: str, value: Any) -> None:
    wrapped = value if envelope == "flat" else [value]

    assert _decode(wrapped, envelope) is None


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_a_non_finite_score_is_refused(constant: str) -> None:
    body = f'[{{"label": "a", "score": {constant}}}]'.encode()

    assert decode_scores(JSON_TYPE, body, envelope="flat") is None


def test_a_two_item_batch_is_refused() -> None:
    assert _decode([TIED, TIED], "single-batch") is None


def test_an_empty_batch_is_refused() -> None:
    assert _decode([], "single-batch") is None


def test_a_flat_body_is_refused_under_the_single_batch_setting() -> None:
    assert _decode(TIED, "single-batch") is None


def test_a_batched_body_is_refused_under_the_flat_setting() -> None:
    assert _decode([TIED], "flat") is None


@pytest.mark.parametrize("content_type", ["text/html", "text/plain", None, "application/jsonx"])
def test_a_non_json_media_type_is_refused(content_type: str | None) -> None:
    assert _decode(TIED, "flat", content_type=content_type) is None


def test_a_json_media_type_with_parameters_decodes() -> None:
    assert _decode(TIED, "flat", content_type="application/json; charset=utf-8") == TIED


def test_too_deep_json_is_refused() -> None:
    body = json.dumps([{"label": "a", "score": 0.5, "extra": json.loads("[" * 40 + "]" * 40)}])

    assert decode_scores(JSON_TYPE, body.encode(), envelope="flat") is None


@pytest.mark.parametrize("body", [b"", b"not json", b"[", b'["\\ud800"]'])
def test_a_body_that_is_not_strict_json_is_refused(body: bytes) -> None:
    assert decode_scores(JSON_TYPE, body, envelope="flat") is None


def test_a_label_with_a_lone_surrogate_is_refused() -> None:
    body = b'[{"label": "\\ud800", "score": 0.5}]'

    assert decode_scores(JSON_TYPE, body, envelope="flat") is None
