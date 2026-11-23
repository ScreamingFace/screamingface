"""Classifier limits, catalog rows, isolation and upstream refusals of choice targets (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — a classifier publishes which inputs it takes and the
# `classifier-limits-v1` bounds it holds; the Gateway refuses a request over a bound before the
# key is read, and fails an answer over one as the provider's error.
# INVARIANT: a limit refusal names the first exceeded key in the C7 order and never a value.
# INVARIANT: two tenants' concurrent choices reach the classifier with their own options and
# their own keys, and each gets its own answer.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from .choice_upstream import (
    LIMITS,
    answering,
    choice_body,
    choice_document,
    choice_input,
    native_answer,
    started_choice,
)
from .classifier_upstream import (
    SCORES,
    ClassifierUpstream,
    classification_body,
    classifier_id,
    classify,
    key_reads,
)
from .conftest import PEER, Harness, put_key, tenant_headers
from .fixtures import ACCOUNT_A, ACCOUNT_B, ENDPOINT_A, ENDPOINT_B, classifier_target

KEYS = {
    (ACCOUNT_A, ENDPOINT_A): "sk-alice-on-a-limits-0001",
    (ACCOUNT_B, ENDPOINT_A): "sk-bob-on-a-limits-0001",
}
MARKER = "zz-limit-marker"
TEXT = f"{MARKER} what is 2 + 2?"


def _attached(client: TestClient, upstream: ClassifierUpstream, *pairs: tuple[str, str]) -> None:
    for account, provider in pairs:
        assert put_key(client, account, provider, KEYS[(account, provider)]).status_code == 200
    upstream.calls.clear()
    upstream.chat.calls.clear()


def _option(label: str = "a", description: str = "d") -> dict[str, str]:
    return {"label": label, "description": description}


# Each input breaks exactly the named limit and every later one in C7 order is broken too, so the
# refusal proves the order: `max_text_chars` first, `max_instructions_chars` last.
OVER: dict[str, dict[str, Any]] = {
    "max_text_chars": choice_input(
        "x" * (LIMITS["max_text_chars"] + 1),
        instructions="i" * (LIMITS["max_instructions_chars"] + 1),
        options=[_option(str(i)) for i in range(LIMITS["max_options"] + 1)],
    ),
    "max_options": choice_input(
        TEXT,
        instructions="i" * (LIMITS["max_instructions_chars"] + 1),
        options=[_option(str(i)) for i in range(LIMITS["max_options"] + 1)],
    ),
    "max_label_bytes": choice_input(
        TEXT,
        # 16 UTF-8 bytes are 5 characters of `é` plus one more byte: code points would pass.
        options=[_option("é" * 8 + "x", "d" * (LIMITS["max_description_chars"] + 1))],
    ),
    "max_description_chars": choice_input(
        TEXT,
        instructions="i" * (LIMITS["max_instructions_chars"] + 1),
        options=[_option("a", "d" * (LIMITS["max_description_chars"] + 1))],
    ),
    "max_instructions_chars": choice_input(
        TEXT, instructions="i" * (LIMITS["max_instructions_chars"] + 1)
    ),
}


@pytest.mark.parametrize(("key", "value"), OVER.items(), ids=OVER.keys())
def test_each_declared_limit_refuses_before_the_key_is_read(
    byom: Harness, key: str, value: dict[str, Any]
) -> None:
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        reads = key_reads(byom.monkeypatch)
        response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, value))

    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": {
            "code": "classifier_limit_exceeded",
            "limit": key,
            "message": f"input exceeds this classifier's {key}",
        }
    }
    assert (reads, upstream.calls) == ([], [])
    assert MARKER not in response.text


def test_an_input_exactly_at_every_limit_is_sent() -> None:
    # The boundary: equal to each limit passes the route's check (pure, no app needed).
    from aigateway.core.classification_input import first_exceeded_limit

    at_limit = choice_input(
        "x" * LIMITS["max_text_chars"],
        instructions="i" * LIMITS["max_instructions_chars"],
        options=[
            _option("é" * 8, "d" * LIMITS["max_description_chars"]),
            *(_option(str(i)) for i in range(LIMITS["max_options"] - 1)),
        ],
    )
    assert first_exceeded_limit(at_limit, LIMITS) is None
    assert first_exceeded_limit("x" * LIMITS["max_text_chars"], LIMITS) is None
    assert first_exceeded_limit("x" * (LIMITS["max_text_chars"] + 1), LIMITS) == "max_text_chars"


HF_LIMITS = {"max_labels": 2, "max_label_bytes": 8, "max_text_chars": 10}


def _hf_document(limits: dict[str, int] | None) -> dict[str, Any]:
    # WHY the default path: the fake answers classifications there only.
    target = classifier_target()
    if limits is not None:
        target["limits"] = limits
    return choice_document(a_target=target, b_target=target)


def test_an_hf_target_with_limits_refuses_long_text_and_fails_a_long_answer(
    byom: Harness,
) -> None:
    with started_choice(byom, _hf_document(HF_LIMITS)) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        long_text = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "x" * 11))
        refused_calls = list(upstream.calls)
        upstream.reply = answering_list([SCORES[:2]])
        at_limit = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "x" * 10))
        upstream.reply = answering_list([SCORES])
        too_many = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "x" * 10))
        upstream.reply = answering_list([[{"label": "POSITIVE+", "score": 0.5}]])
        long_label = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "x"))

    assert long_text.status_code == 400, long_text.text
    assert long_text.json()["detail"]["limit"] == "max_text_chars"
    assert refused_calls == []
    assert at_limit.status_code == 200, at_limit.text
    assert at_limit.json()["scores"] == SCORES[:2]
    # SCORES has three labels and `POSITIVE+` nine bytes; this target allows two and eight.
    for failed in (too_many, long_label):
        assert failed.status_code == 502, failed.text
        assert failed.json()["detail"] == {
            "code": "provider_error",
            "message": "The remote endpoint response is invalid.",
        }


def test_an_hf_target_without_limits_accepts_what_it_accepts_today(byom: Harness) -> None:
    with started_choice(byom, _hf_document(None)) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "x" * 50_000))

    assert response.status_code == 200, response.text
    assert response.json()["scores"] == SCORES


def answering_list(body: list[Any]):
    def reply(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=body)

    return reply


def test_the_catalog_shows_input_contracts_and_strict_limits(byom: Harness) -> None:
    doc = choice_document(with_hf=True)
    doc["endpoints"][1]["targets"][2]["limits"] = dict(HF_LIMITS)
    with started_choice(byom, doc) as (client, upstream):
        listed = client.get("/v1/classifiers", headers=tenant_headers(ACCOUNT_A))
        details = client.get(
            "/v1/classifiers/details",
            params={"model": f"{ENDPOINT_A}/router_v1"},
            headers=tenant_headers(ACCOUNT_A),
        )
        calls = list(upstream.calls)

    assert listed.status_code == 200, listed.text
    rows = {row["id"]: row for row in listed.json()["data"]}
    choice_limits = {"contract": "classifier-limits-v1", **LIMITS}
    assert rows[f"{ENDPOINT_A}/router_v1"] == {
        "object": "classifier",
        "id": f"{ENDPOINT_A}/router_v1",
        "owned_by": ENDPOINT_A,
        "task": "text-classification",
        "contract": "systemone-choice-v1",
        "input_contracts": ["choice"],
        "limits": choice_limits,
    }
    assert list(rows[f"{ENDPOINT_A}/router_v1"]["limits"]) == [
        "contract",
        "max_labels",
        "max_label_bytes",
        "max_text_chars",
        "max_options",
        "max_description_chars",
        "max_instructions_chars",
    ]
    assert rows[classifier_id(ENDPOINT_A)]["input_contracts"] == ["text"]
    assert rows[classifier_id(ENDPOINT_A)]["limits"] is None
    assert rows[classifier_id(ENDPOINT_B)]["limits"] == {
        "contract": "classifier-limits-v1",
        **HF_LIMITS,
    }
    assert details.status_code == 200, details.text
    assert details.json()["input_contracts"] == ["choice"]
    assert details.json()["limits"] == choice_limits
    assert "upstream_model" not in listed.text and "request_path" not in listed.text
    assert calls == []


def _echo_options(request: httpx.Request) -> httpx.Response:
    """Answer with the request's own labels and a bearer-derived score, to prove no mixing."""
    sent = json.loads(request.content)
    labels = list(sent["questions"]["choice"]["criteria"])
    score = 0.25 if request.headers["authorization"].endswith("alice-on-a-limits-0001") else 0.75
    return httpx.Response(200, json=native_answer(dict.fromkeys(labels, score)))


def test_concurrent_choices_with_different_options_and_keys_never_mix(byom: Harness) -> None:
    calls = [
        (ACCOUNT_A, ["alpha", "beta", "gamma"]),
        (ACCOUNT_B, ["one", "two", "three", "four"]),
    ]
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A), (ACCOUNT_B, ENDPOINT_A))
        upstream.reply = _echo_options
        upstream.expect_overlap(len(calls))

        async def overlap() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=client.app, client=PEER)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                requests = [
                    http.post(
                        "/v1/classifications",
                        json=choice_body(
                            ENDPOINT_A,
                            choice_input(TEXT, options=[_option(label) for label in labels]),
                        ),
                        headers=tenant_headers(account),
                    )
                    for account, labels in calls
                ]
                return list(await asyncio.gather(*requests))

        assert client.portal is not None
        responses = client.portal.call(overlap)
        sent = {call.bearer: json.loads(call.body) for call in upstream.calls}

    assert [r.status_code for r in responses] == [200, 200]
    assert [[s["label"] for s in r.json()["scores"]] for r in responses] == [
        labels for _account, labels in calls
    ]
    assert [{s["score"] for s in r.json()["scores"]} for r in responses] == [{0.25}, {0.75}]
    for account, labels in calls:
        body = sent[f"Bearer {KEYS[(account, ENDPOINT_A)]}"]
        assert list(body["questions"]["choice"]["criteria"]) == labels


@pytest.mark.parametrize("status", [413, 422, 400, 500])
def test_an_upstream_refusal_is_the_provider_error_without_its_body(
    byom: Harness, status: int
) -> None:
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        upstream.reply = lambda _request: httpx.Response(status, json={"detail": MARKER})
        response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, choice_input(TEXT)))

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "provider_error"
    assert MARKER not in response.text


@pytest.mark.parametrize(
    "answer",
    [
        native_answer({"a": 0.5}, usage={"truncated": True}),
        native_answer({"a": 1.0}, error={"message": "failed"}),
        {"answers": {"choice": {"type": "choice", "probabilities": {"a": 1.0}, "error": "x"}}},
    ],
    ids=["truncated-input", "error-beside-the-answers", "error-on-the-answer"],
)
def test_a_malformed_answer_through_the_app_is_the_provider_error(
    byom: Harness, answer: dict[str, Any]
) -> None:
    with started_choice(byom, choice_document()) as (client, upstream):
        _attached(client, upstream, (ACCOUNT_A, ENDPOINT_A))
        upstream.reply = answering(answer)
        response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, choice_input(TEXT)))

    assert response.status_code == 502, response.text
    assert response.json()["detail"] == {
        "code": "provider_error",
        "message": "The remote endpoint response is invalid.",
    }
