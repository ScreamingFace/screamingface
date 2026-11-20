"""`X-AIGW-Upstream-Attempts` through the real app for configured endpoints (contract C7).

# FEATURE: Router Recipe extension Unit 5.1, test-plan §4 item 8 — the header origin matrix on
# both routes: `0` before upstream I/O, `n` after `n` physical sends, status and body unchanged.
# INVARIANT: the remote-endpoint client has transport retries `0`; only the Gateway's own overload
# retry sends a request again, and that send is counted.
"""

from __future__ import annotations

from collections.abc import Iterator
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
    ClassifierUpstream,
    classification_body,
    classify,
    mixed_document,
    started,
)
from .conftest import Harness, chat, put_key, tenant_headers
from .fixtures import ACCOUNT_A, ACCOUNT_B, ENDPOINT_A, ENDPOINT_B

HEADER = "x-aigw-upstream-attempts"
KEY = "sk-alice-on-a-attempts-0001"


@pytest.fixture
def quick_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("AIGW_RETRY_BACKOFF_BASE", "0")
    monkeypatch.setenv("AIGW_RETRY_JITTER", "0")


@pytest.fixture
def mixed(byom: Harness) -> Iterator[tuple[TestClient, ClassifierUpstream]]:
    with started(byom, mixed_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        upstream.calls.clear()
        byom.upstream.calls.clear()
        yield client, upstream


@pytest.fixture
def choices(byom: Harness) -> Iterator[tuple[TestClient, ClassifierUpstream]]:
    with started_choice(byom, choice_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        upstream.calls.clear()
        yield client, upstream


def test_a_chat_is_one_attempt(byom: Harness, mixed: tuple[TestClient, Any]) -> None:
    client, _upstream = mixed

    response = chat(client, ACCOUNT_A, ENDPOINT_A)

    assert response.status_code == 200, response.text
    assert len(byom.upstream.calls) == 1
    assert response.headers[HEADER] == "1"


def test_a_text_classification_is_one_attempt(mixed: tuple[TestClient, Any]) -> None:
    client, upstream = mixed

    response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "classify me"))

    assert response.status_code == 200, response.text
    assert len(upstream.calls) == 1
    assert response.headers[HEADER] == "1"


def test_a_choice_classification_is_one_attempt(choices: tuple[TestClient, Any]) -> None:
    client, upstream = choices
    upstream.reply = answering(native_answer({"math": 0.7, "general": 0.2, "LABEL_0": 0.1}))

    response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, choice_input()))

    assert response.status_code == 200, response.text
    assert len(upstream.calls) == 1
    assert response.headers[HEADER] == "1"


def test_an_upstream_error_counts_its_send(mixed: tuple[TestClient, Any]) -> None:
    client, upstream = mixed
    upstream.reply = lambda _request: httpx.Response(500, json={"error": "down"})

    response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "classify me"))

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "provider_error"
    assert len(upstream.calls) == 1
    assert response.headers[HEADER] == "1"


def test_the_gateway_overload_retry_is_another_attempt(quick_retry: None, byom: Harness) -> None:
    answers = iter([httpx.Response(429, json={"error": "busy"}), httpx.Response(200, json=[[]])])
    with started(byom, mixed_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        upstream.calls.clear()
        upstream.reply = lambda _request: next(answers)
        response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "classify me"))

    # The second answer is a bad result, so the call fails after two counted sends.
    assert response.status_code == 502, response.text
    assert len(upstream.calls) == 2
    assert response.headers[HEADER] == "2"


def test_a_transport_failure_counts_the_uncertain_send(mixed: tuple[TestClient, Any]) -> None:
    client, upstream = mixed

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    upstream.reply = refuse

    response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, "classify me"))

    assert response.status_code >= 500, response.text
    assert len(upstream.calls) == 1
    assert response.headers[HEADER] == "1"


@pytest.mark.parametrize(
    ("account", "body"),
    [
        (ACCOUNT_B, classification_body(ENDPOINT_A, "no key attached")),
        (ACCOUNT_B, classification_body(ENDPOINT_B, "not granted")),
        (ACCOUNT_A, classification_body(ENDPOINT_A, "x", alias="no_such_alias")),
        (ACCOUNT_A, {"model": 7, "input": "malformed model"}),
        (ACCOUNT_A, {"model": f"{ENDPOINT_A}/classifier_v1", "input": choice_input()}),
    ],
    ids=["missing-connection", "grant-refusal", "unknown-model", "malformed", "unsupported-input"],
)
def test_a_classification_refused_before_any_send_is_zero(
    mixed: tuple[TestClient, Any], account: str, body: dict[str, Any]
) -> None:
    client, upstream = mixed

    response = classify(client, account, body)

    assert 400 <= response.status_code < 500, response.text
    assert upstream.calls == []
    assert response.headers[HEADER] == "0"


def test_a_choice_limit_refusal_is_zero(choices: tuple[TestClient, Any]) -> None:
    client, upstream = choices
    too_long = choice_input("x" * (LIMITS["max_text_chars"] + 1))

    response = classify(client, ACCOUNT_A, choice_body(ENDPOINT_A, too_long))

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "classifier_limit_exceeded"
    assert upstream.calls == []
    assert response.headers[HEADER] == "0"


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/classifications"])
def test_an_unauthenticated_call_is_zero(mixed: tuple[TestClient, Any], path: str) -> None:
    client, _upstream = mixed

    response = client.post(path, json={"model": f"{ENDPOINT_A}/x", "input": "hi"})

    assert response.status_code == 401, response.text
    assert response.headers[HEADER] == "0"


def test_a_body_over_the_cap_is_zero(byom: Harness) -> None:
    byom.monkeypatch.setenv("AIGW_MAX_REQUEST_BYTES", "1024")
    with started(byom, mixed_document()) as (client, upstream):
        response = client.post(
            "/v1/classifications",
            json={"model": f"{ENDPOINT_A}/classifier_v1", "input": "x" * 4096},
            headers=tenant_headers(ACCOUNT_A),
        )

    assert response.status_code == 413, response.text
    assert upstream.calls == []
    assert response.headers[HEADER] == "0"
