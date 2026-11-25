"""Answer one question with the model a routing profile selects, through `/route-answer` (OME-1823).

FEATURE (BYOM routing pilot, spec 3.6): `Client.route_answer` sends a routing profile ID and one
question to the Engine's `/route-answer`. The Engine classifies the question, takes the one
highest label and asks that label's chat model once; the SDK returns the answer with the scores
and the selected label and model, after checking the whole result.
STORY: as a researcher with a router and three expert models connected, I call
`client.route_answer("expert_router_v1", question)` and get the selected expert's answer, or a
plain reason why not, and I am told whether asking again could bill the models again.

This file covers the request, the result and the surface; `test_route_answer_errors.py` covers
the error table and the artifact path.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import httpx
import pytest
from _route_answer_fixtures import (
    CLASSIFIER,
    CODE_MODEL,
    PROFILE,
    REVISION,
    answering,
    engine_client,
    ok,
    route,
    route_error,
    routed_result,
    with_classification,
    with_scores,
    with_selected,
)
from url4.wire.subrequest import decode_subrequest, encode_subrequest

import screamingface as sf
from screamingface._core.wire import _REPLAY_SAFE
from screamingface.classification import LabelScore
from screamingface.errors import ExecutionError, PlanningError
from screamingface.routing import RoutedAnswer

# --- the request ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Why is the sky blue?",
        "1 + 1 = 2 & done",
        'She said "no" (twice), it\'s 100% #1 !route-answer',
        "line one\nline two\ttab",
        "café 中文 \U0001f600",
        "a $1 reference and %41",
    ],
)
def test_the_profile_and_question_reach_the_engine_byte_for_byte(text: str) -> None:
    result, requests = route(ok, text)

    assert isinstance(result, RoutedAnswer)
    (request,) = requests
    path, _, query = request.url.raw_path.decode("ascii").partition("?")
    assert (request.method, path) == ("GET", "/route-answer")
    assert query.startswith("q=")
    context, intent = decode_subrequest(query.removeprefix("q="))
    assert intent == "route-answer"
    # INVARIANT: the context is exactly the two fields; the Engine refuses anything else.
    assert json.loads(context) == {"profile": PROFILE, "input": text}


def test_the_call_is_one_get_never_marked_safe_to_replay() -> None:
    _, requests = route(ok)

    (request,) = requests
    assert request.extensions.get(_REPLAY_SAFE, False) is False


def test_the_call_states_a_60_second_wait_and_reads_for_75() -> None:
    _, requests = route(ok)

    (request,) = requests
    assert request.headers["Prefer"] == "wait=60"
    assert request.extensions["timeout"]["read"] == 75.0


def _encoded_size(text: str) -> int:
    """The bytes the Engine counts: path and query as httpx puts them on the wire."""

    context = json.dumps(
        {"profile": PROFILE, "input": text}, ensure_ascii=False, separators=(",", ":")
    )
    path = encode_subrequest("/route-answer", context, "route-answer")
    return len(httpx.URL(path).raw_path)


@pytest.mark.parametrize("character", ["a", '"', "\u0436", "\U0001f600"])
def test_the_largest_question_that_fits_is_sent_and_one_more_is_refused_first(
    character: str,
) -> None:
    base, one = _encoded_size(""), _encoded_size(character)
    largest = (8192 - base) // (one - base)
    assert _encoded_size(character * largest) <= 8192 < _encoded_size(character * (largest + 1))

    requests: list[httpx.Request] = []
    with engine_client(ok, requests) as client:
        client.route_answer(PROFILE, character * largest)
        with pytest.raises(PlanningError) as caught:
            client.route_answer(PROFILE, character * (largest + 1))

    assert len(requests) == 1
    assert len(requests[0].url.raw_path) <= 8192
    error = caught.value
    assert (error.code, error.permanent) == ("uri_too_long", True)
    assert error.details == {
        "encoded_bytes": _encoded_size(character * (largest + 1)),
        "limit_bytes": 8192,
    }
    assert character * largest not in error.message


@pytest.mark.parametrize(
    ("profile", "text"), [(None, "text"), (PROFILE, None), (PROFILE, 3), (b"p", "text")]
)
def test_a_non_string_profile_or_question_is_refused_before_any_request(
    profile: Any, text: Any
) -> None:
    requests: list[httpx.Request] = []
    with engine_client(ok, requests) as client, pytest.raises(TypeError):
        client.route_answer(profile, text)

    assert requests == []


@pytest.mark.parametrize(
    ("profile", "text", "field"),
    [
        ("expert\ud800", "text", "profile ID"),
        (PROFILE, "secret \udc00 text", "input text"),
    ],
)
def test_text_that_utf8_cannot_encode_is_refused_naming_the_field_only(
    profile: str, text: str, field: str
) -> None:
    requests: list[httpx.Request] = []
    with engine_client(ok, requests) as client, pytest.raises(PlanningError) as caught:
        client.route_answer(profile, text)

    assert requests == []
    error = caught.value
    assert (error.code, error.permanent) == ("malformed_source", True)
    assert field in error.message
    assert "secret" not in error.message and "expert" not in error.message


# --- the result -------------------------------------------------------------------------------


def test_the_result_carries_the_answer_scores_and_selection_in_order() -> None:
    result, _ = route(ok)

    assert result == RoutedAnswer(
        profile=PROFILE,
        revision=REVISION,
        policy="unique-argmax-v1",
        contract="routed-answer-v1",
        classifier=CLASSIFIER,
        scores=(
            LabelScore("general", 0.07),
            LabelScore("code", 0.91),
            LabelScore("math", 0.02),
        ),
        selected_label="code",
        selected_model=CODE_MODEL,
        answer="Use a list comprehension.",
    )


def test_the_result_type_is_frozen_with_the_spec_field_order() -> None:
    assert [field.name for field in dataclasses.fields(RoutedAnswer)] == [
        "profile",
        "revision",
        "policy",
        "contract",
        "classifier",
        "scores",
        "selected_label",
        "selected_model",
        "answer",
    ]
    result, _ = route(ok)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.answer = "changed"  # type: ignore[misc]


def test_integer_scores_are_numbers_and_the_answer_may_be_empty() -> None:
    body = routed_result(answer="")
    body["classification"] = {
        **body["classification"],
        "scores": [{"label": "code", "score": 1}, {"label": "math", "score": 0}],
    }

    result, _ = route(answering(200, body))

    assert isinstance(result, RoutedAnswer)
    assert result.scores == (LabelScore("code", 1.0), LabelScore("math", 0.0))
    assert result.answer == ""


_MALFORMED: dict[str, object] = {
    "not-json": b"{not json",
    "not-an-object": b"[]",
    "wrong-object": routed_result(object="classification"),
    "wrong-contract": routed_result(contract="routed-answer-v2"),
    "wrong-policy": routed_result(policy="top-k-v1"),
    "wrong-classification-contract": with_classification(contract="classification-scores-v2"),
    "another-profile": routed_result(profile="other_router_v1"),
    "revision-not-a-string": routed_result(revision=None),
    "revision-without-prefix": routed_result(revision="ab" * 32),
    "revision-uppercase": routed_result(revision="sha256:" + "AB" * 32),
    "revision-short": routed_result(revision="sha256:" + "a" * 63),
    "revision-not-hex": routed_result(revision="sha256:" + "g" * 64),
    "missing-answer": {k: v for k, v in routed_result().items() if k != "answer"},
    "answer-not-a-string": routed_result(answer=None),
    "classification-not-an-object": routed_result(classification=[]),
    "classifier-not-a-string": with_classification(model=7),
    "classifier-empty": with_classification(model=""),
    "selected-not-an-object": routed_result(selected="code"),
    "selected-model-empty": with_selected(model=""),
    "selected-model-not-a-string": with_selected(model=None),
    "selected-label-not-a-string": with_selected(label=1),
    "scores-not-a-list": with_classification(scores={"code": 0.9}),
    "scores-empty": with_classification(scores=[]),
    "score-item-not-an-object": with_classification(scores=["code"]),
    "duplicate-label": with_scores(("code", 0.6), ("code", 0.4)),
    "empty-label": with_scores(("code", 0.9), ("", 0.1)),
    "label-not-a-string": with_scores(("code", 0.9), (3, 0.1)),
    "boolean-score": with_scores(("code", True), ("math", 0.0)),
    "string-score": with_scores(("code", "0.9"), ("math", 0.1)),
    "score-above-one": with_scores(("code", 1.5), ("math", 0.1)),
    "score-below-zero": with_scores(("code", 0.9), ("math", -0.01)),
    "selected-not-the-highest": with_scores(("code", 0.2), ("math", 0.8)),
    "selected-tied-for-highest": with_scores(("code", 0.5), ("math", 0.5)),
    "selected-not-scored": with_scores(("general", 0.2), ("math", 0.8), label="code"),
}


@pytest.mark.parametrize("body", _MALFORMED.values(), ids=_MALFORMED.keys())
def test_a_result_breaking_one_rule_is_a_contract_error(body: object) -> None:
    handler = (
        (lambda _request: httpx.Response(200, content=body))
        if isinstance(body, bytes)
        else answering(200, body)
    )

    error = route_error(handler)

    assert isinstance(error, ExecutionError)
    assert (error.code, error.retryable) == ("engine_contract_error", False)


@pytest.mark.parametrize("literal", ["1e999", "-1e999", "NaN", "Infinity", "1" + "0" * 400])
def test_a_score_that_is_not_a_finite_number_is_a_contract_error(literal: str) -> None:
    body = json.dumps(routed_result()).replace('"score": 0.91', f'"score": {literal}')
    assert literal in body

    error = route_error(lambda _request: httpx.Response(200, content=body.encode()))

    assert isinstance(error, ExecutionError)
    assert error.code == "engine_contract_error"


# --- the surface ------------------------------------------------------------------------------


def test_a_closed_client_refuses_to_route_an_answer() -> None:
    requests: list[httpx.Request] = []
    client = engine_client(ok, requests)
    client.close()

    with pytest.raises(RuntimeError, match="closed"):
        client.route_answer(PROFILE, "question")
    assert requests == []


def test_the_routed_answer_type_is_exported_and_the_call_is_on_client_only() -> None:
    """Spec section 6, D2: `Client.route_answer` only; no module function, no async method."""

    assert sf.RoutedAnswer is RoutedAnswer
    assert "RoutedAnswer" in sf.__all__
    assert not hasattr(sf, "route_answer")
    assert not hasattr(sf.AsyncClient, "route_answer")
