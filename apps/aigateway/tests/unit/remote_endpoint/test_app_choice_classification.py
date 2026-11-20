"""`POST /v1/classifications` with a structured-choice input, through the real app (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — a Router asks one `systemone-choice-v1` classifier to
# pick among its candidates' labels; the Gateway sends one native SystemOne question and returns
# the label probabilities as `classification-scores-v1`, in the order the upstream returned them.
# STORY: as an Engine routing a question, I send the candidates' labels and descriptions; the
# classifier sees them in my order, and I read its probabilities without any recalculation.
# INVARIANT: the criteria follow `options` order and the scores follow the answer's key order;
# nothing is sorted on either side.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .choice_upstream import (
    INSTRUCTIONS,
    OPTIONS,
    answering,
    choice_body,
    choice_document,
    choice_input,
    choice_target,
    native_answer,
    started_choice,
)
from .classifier_upstream import ClassifierUpstream, classify, key_reads
from .conftest import Harness, put_key
from .fixtures import ACCOUNT_A, ACCOUNT_B, CLASSIFIER_PATH, ENDPOINT_A, ORIGIN_A

KEY = "sk-alice-on-a-choice-0001"
# A value no refusal may repeat.
MARKER = "zz-choice-marker"
TEXT = 'What is 17 times 23? "quoted" café 東京'
# Returned in neither option order nor sorted order.
PROBABILITIES = {"math": 0.6, "general": 0.1, "LABEL_0": 0.3}


def test_a_choice_target_gets_one_native_question_and_its_scores_keep_returned_order(
    byom: Harness,
) -> None:
    with started_choice(byom, choice_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        upstream.calls.clear()
        upstream.reply = answering(native_answer(PROBABILITIES))
        response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, choice_input(TEXT)))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "object": "classification",
        "model": f"{ENDPOINT_A}/router_v1",
        "contract": "classification-scores-v1",
        "scores": [
            {"label": "math", "score": 0.6},
            {"label": "general", "score": 0.1},
            {"label": "LABEL_0", "score": 0.3},
        ],
    }
    (call,) = upstream.calls
    assert (call.url, call.bearer) == (ORIGIN_A + CLASSIFIER_PATH, f"Bearer {KEY}")
    sent = json.loads(call.body)
    assert sent == {
        "state": {"body": TEXT},
        "questions": {
            "choice": {
                "type": "choice",
                "instructions": INSTRUCTIONS,
                "criteria": {option["label"]: option["description"] for option in OPTIONS},
            }
        },
    }
    assert list(sent["questions"]["choice"]["criteria"]) == ["general", "LABEL_0", "math"]


def test_a_configured_upstream_model_is_sent_first_as_model(byom: Harness) -> None:
    doc = choice_document(a_target=choice_target(upstream_model="jev/router-2026-10"))
    with started_choice(byom, doc) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        upstream.calls.clear()
        upstream.reply = answering(native_answer(PROBABILITIES))
        response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, choice_input(TEXT)))

    assert response.status_code == 200, response.text
    (call,) = upstream.calls
    sent = json.loads(call.body)
    assert list(sent) == ["model", "state", "questions"]
    assert sent["model"] == "jev/router-2026-10"


def _attached(client: TestClient, upstream: ClassifierUpstream, *pairs: tuple[str, str]) -> None:
    for account, provider in pairs:
        assert put_key(client, account, provider, KEYS[(account, provider)]).status_code == 200
    # WHY both fakes: the readiness probe of the chat validation target reaches the chat fake.
    upstream.calls.clear()
    upstream.chat.calls.clear()


KEYS = {
    (ACCOUNT_A, ENDPOINT_A): KEY,
    (ACCOUNT_B, ENDPOINT_A): "sk-bob-on-a-choice-0001",
}
LABEL_SETS = {
    "three": ["general", "LABEL_0", "math"],
    "four": ["LABEL_3", "LABEL_1", "LABEL_0", "LABEL_2"],
    "five": ["zeta", "alpha", "Écrire", "x-y_z.1", "東京"],
}


def _options(labels: list[str]) -> list[dict[str, str]]:
    return [{"label": label, "description": f"about {label}"} for label in labels]


def test_differently_sized_choices_reach_one_service_in_their_own_order(byom: Harness) -> None:
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        upstream.reply = answering(native_answer({"general": 1.0}))
        responses = [
            classify(
                client,
                ACCOUNT_A,
                choice_body(ENDPOINT_A, choice_input(TEXT, options=_options(labels))),
            )
            for labels in LABEL_SETS.values()
        ]

    assert [r.status_code for r in responses] == [200, 200, 200]
    sent = [json.loads(call.body)["questions"]["choice"]["criteria"] for call in upstream.calls]
    assert [list(criteria) for criteria in sent] == list(LABEL_SETS.values())
    assert sent[1]["LABEL_0"] == "about LABEL_0"


def test_a_label_outside_the_options_is_returned_unchanged(byom: Harness) -> None:
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        upstream.reply = answering(native_answer({"other": 0.7, "math": 0.3}))
        response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, choice_input(TEXT)))

    assert response.status_code == 200, response.text
    assert response.json()["scores"] == [
        {"label": "other", "score": 0.7},
        {"label": "math", "score": 0.3},
    ]


@pytest.mark.parametrize(
    ("alias", "value"),
    [("classifier_v1", choice_input(TEXT)), ("router_v1", TEXT)],
    ids=["object-to-text-target", "text-to-choice-target"],
)
def test_an_input_the_target_does_not_take_is_unsupported_before_any_key_or_io(
    byom: Harness, alias: str, value: Any
) -> None:
    with started_choice(byom, choice_document(with_hf=True)) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        reads = key_reads(byom.monkeypatch)
        response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, value, alias))

    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": {
            "code": "unsupported_input",
            "message": "this classifier does not take this kind of input",
        }
    }
    assert (reads, upstream.calls, byom.upstream.calls) == ([], [], [])
    assert MARKER not in response.text


INVALID_CHOICES: dict[str, Any] = {
    "unknown-key": choice_input(TEXT, extra=MARKER),
    "missing-options": {k: v for k, v in choice_input(TEXT).items() if k != "options"},
    "other-contract": {**choice_input(TEXT), "contract": "classification-choice-input-v2"},
    "number-text": {**choice_input(TEXT), "text": 7},
    "empty-instructions": choice_input(TEXT, instructions=""),
    "empty-options": choice_input(TEXT, options=[]),
    "option-extra-key": choice_input(
        TEXT, options=[{"label": "a", "description": "d", MARKER: "x"}]
    ),
    "empty-label": choice_input(TEXT, options=[{"label": "", "description": "d"}]),
    "control-label": choice_input(TEXT, options=[{"label": "a\nb", "description": "d"}]),
    "duplicate-label": choice_input(
        TEXT, options=[{"label": MARKER, "description": "d"}, {"label": MARKER, "description": "e"}]
    ),
    "empty-description": choice_input(TEXT, options=[{"label": "a", "description": ""}]),
    "number-description": choice_input(TEXT, options=[{"label": "a", "description": 3}]),
    "options-not-a-list": {**choice_input(TEXT), "options": {"a": "d"}},
}


@pytest.mark.parametrize("value", INVALID_CHOICES.values(), ids=INVALID_CHOICES.keys())
def test_a_malformed_choice_is_invalid_before_any_provider_lookup(
    byom: Harness, value: Any
) -> None:
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        reads = key_reads(byom.monkeypatch)
        unknown = classify(client, ACCOUNT_A, choice_body("byom_" + "c" * 32, value))
        response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, value))

    for refused in (response, unknown):
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"]["code"] == "invalid_request"
        assert MARKER not in refused.text
    assert (reads, upstream.calls) == ([], [])


def test_a_lone_surrogate_in_a_choice_is_invalid(byom: Harness) -> None:
    raw = json.dumps(choice_body(ENDPOINT_A, choice_input("ab"))).replace('"ab"', '"a\\ud800"')
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        response = classify(client, ACCOUNT_A, None, raw=raw.encode())

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "invalid_request"
    assert upstream.calls == []


@pytest.mark.parametrize(
    "raw_model",
    ["7", "null", '"byom_x\\ud800/router_v1"'],
    ids=["number", "null", "lone-surrogate"],
)
def test_a_choice_with_a_malformed_model_is_invalid_before_any_lookup(
    byom: Harness, raw_model: str
) -> None:
    value = json.dumps(choice_input(TEXT))
    raw = f'{{"model": {raw_model}, "input": {value}}}'.encode()
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        reads = key_reads(byom.monkeypatch)
        response = classify(client, ACCOUNT_A, None, raw=raw)

    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": {"code": "invalid_request", "message": "model must be a valid Unicode string"}
    }
    assert (reads, upstream.calls) == ([], [])
