"""`POST /v1/classifications` through the real app: the success path and every refusal before I/O.

# FEATURE: hosted BYOM Unit 3 — an account sends a classifier ID and a text; the Gateway calls the
# configured classifier with that account's own Connection and returns the labels and scores
# unchanged, ties in upstream order.
# STORY: as a tenant granted an endpoint, I classify a text with its classifier and my own key;
# another tenant cannot use or probe it, and no other request reaches the upstream.
# INVARIANT (spec G6): body shape, then the provider and the INVOKE grant, then the classifier,
# then credentials; a refusal at any of these steps reads no key and sends nothing upstream.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from aigateway.core.registry import ProviderRegistry
from aigateway.routes import classifications

from .classifier_upstream import (
    SCORES,
    classification_body,
    classifier_id,
    classify,
    gateway_log,
    key_reads,
    messages_of,
    mixed_document,
    sent_input,
    started,
)
from .conftest import PEER, Harness, chat, chat_body, put_key, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ALIAS,
    CLASSIFIER_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
)

KEY = {
    (ACCOUNT_A, ENDPOINT_A): "sk-alice-on-a-classify-0001",
    (ACCOUNT_A, ENDPOINT_B): "sk-alice-on-b-classify-0001",
    (ACCOUNT_B, ENDPOINT_A): "sk-bob-on-a-classify-0001",
}
URL = {ENDPOINT_A: ORIGIN_A + CLASSIFIER_PATH, ENDPOINT_B: ORIGIN_B + CLASSIFIER_PATH}
MARKER = "zz-input-marker"
TEXT = f'{MARKER}: line one\nline "two" + three & café 東京 🙂'
UNREGISTERED = "byom_" + "c" * 32


def _attach(client: Any, byom: Harness, *pairs: tuple[str, str]) -> None:
    for account, provider in pairs or tuple(KEY):
        response = put_key(client, account, provider, KEY[(account, provider)])
        assert response.status_code == 200, response.text
    byom.upstream.calls.clear()


def test_a_classification_reaches_the_classifier_and_returns_its_scores(byom: Harness) -> None:
    with started(byom, mixed_document()) as (client, upstream):
        _attach(client, byom, (ACCOUNT_A, ENDPOINT_A))
        reads = key_reads(byom.monkeypatch)
        response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, TEXT))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "object": "classification",
        "model": classifier_id(ENDPOINT_A),
        "contract": "classification-scores-v1",
        "scores": SCORES,
    }
    (call,) = upstream.calls
    assert (call.url, call.bearer, call.probe) == (
        URL[ENDPOINT_A],
        f"Bearer {KEY[(ACCOUNT_A, ENDPOINT_A)]}",
        False,
    )
    assert sent_input(call) == {"inputs": TEXT}
    assert byom.upstream.calls == []
    # WHY: proves the spy sees the key read that every refused request below never made.
    assert reads


def test_the_flat_envelope_is_served_when_configured(byom: Harness) -> None:
    with started(byom, mixed_document(envelope="flat")) as (client, upstream):
        upstream.reply = lambda _request: httpx.Response(200, json=SCORES)
        _attach(client, byom, (ACCOUNT_A, ENDPOINT_A))
        response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, TEXT))

    assert response.status_code == 200, response.text
    assert response.json()["scores"] == SCORES


def _body(**fields: Any) -> dict[str, Any]:
    return {**classification_body(ENDPOINT_A, TEXT), **fields}


# (account, JSON body or raw bytes, status, code or detail text)
REFUSALS: dict[str, tuple[str, Any, int, str]] = {
    "not-json": (ACCOUNT_A, b"{not json", 400, "request body must be valid JSON"),
    "not-an-object": (ACCOUNT_A, [_body()], 400, "invalid_request"),
    "number-model": (ACCOUNT_A, _body(model=7), 400, "invalid_request"),
    "list-input": (ACCOUNT_A, _body(input=[TEXT]), 400, "invalid_request"),
    "null-input": (ACCOUNT_A, _body(input=None), 400, "invalid_request"),
    "no-input": (ACCOUNT_A, {"model": classifier_id(ENDPOINT_A)}, 400, "invalid_request"),
    "no-model": (ACCOUNT_A, {"input": TEXT}, 400, "invalid_request"),
    # WHY raw bytes: `json.dumps` escapes the lone surrogate, so the body is valid JSON that
    # decodes to a string no UTF-8 request to the classifier can carry.
    "surrogate-input": (
        ACCOUNT_A,
        json.dumps(_body(input=f"{MARKER} \ud800 tail")).encode(),
        400,
        "invalid_request",
    ),
    "surrogate-model": (
        ACCOUNT_A,
        json.dumps(_body(model=classifier_id(ENDPOINT_A) + "\udfff")).encode(),
        400,
        "invalid_request",
    ),
    "no-prefix": (ACCOUNT_A, _body(model="classifier_v1"), 400, "model must be provider-prefixed"),
    "seed": (ACCOUNT_A, _body(seed=7), 400, "unsupported_parameters"),
    "top_k": (ACCOUNT_A, _body(top_k=2), 400, "unsupported_parameters"),
    "function_to_apply": (
        ACCOUNT_A,
        _body(function_to_apply="none"),
        400,
        "unsupported_parameters",
    ),
    "stream": (ACCOUNT_A, _body(stream=False), 400, "unsupported_parameters"),
    "absent-provider": (
        ACCOUNT_A,
        _body(model=classifier_id(UNREGISTERED)),
        400,
        f"unknown provider: {UNREGISTERED}",
    ),
    "ungranted-provider": (
        ACCOUNT_B,
        _body(model=classifier_id(ENDPOINT_B)),
        400,
        f"unknown provider: {ENDPOINT_B}",
    ),
    "unknown-alias": (ACCOUNT_A, _body(model=f"{ENDPOINT_A}/undeclared_v1"), 400, "invalid_model"),
    "chat-alias": (ACCOUNT_A, _body(model=f"{ENDPOINT_A}/{ALIAS}"), 400, "invalid_model"),
    "bundled-provider": (ACCOUNT_A, _body(model="openai/gpt-4o-mini"), 400, "invalid_model"),
}


def _detail_text(response: httpx.Response) -> str:
    detail = response.json()["detail"]
    return detail if isinstance(detail, str) else detail["code"]


@pytest.mark.parametrize("case", REFUSALS.values(), ids=REFUSALS.keys())
def test_a_refusal_reads_no_key_and_sends_nothing(
    byom: Harness, case: tuple[str, Any, int, str]
) -> None:
    account, body, status, expected = case
    with started(byom, mixed_document()) as (client, upstream):
        _attach(client, byom)
        reads = key_reads(byom.monkeypatch)
        if isinstance(body, bytes):
            response = classify(client, account, None, raw=body)
        else:
            response = classify(client, account, body)

    assert (response.status_code, _detail_text(response)) == (status, expected), response.text
    assert (reads, upstream.calls, byom.upstream.calls) == ([], [], [])
    assert MARKER not in response.text


def test_a_body_nested_past_the_decoder_s_depth_is_the_malformed_body_400(byom: Harness) -> None:
    """INVARIANT: such a body makes the JSON decoder raise RecursionError, not ValueError; it is
    still the caller's malformed-body 400, before any provider lookup, key read or upstream call,
    and the body reaches neither the answer nor a log record."""

    depth = 10_000
    raw = b"[" * depth + json.dumps(MARKER).encode() + b"]" * depth
    lookups: list[str] = []
    original = ProviderRegistry.get

    def spy(self: ProviderRegistry, custom_llm_provider: str) -> Any:
        lookups.append(custom_llm_provider)
        return original(self, custom_llm_provider)

    with started(byom, mixed_document()) as (client, upstream):
        _attach(client, byom)
        reads = key_reads(byom.monkeypatch)
        byom.monkeypatch.setattr(ProviderRegistry, "get", spy)
        with gateway_log() as records:
            response = classify(client, ACCOUNT_A, None, raw=raw)
        refused = (list(lookups), list(reads), list(upstream.calls), list(byom.upstream.calls))
        # WHY a control call: proves the spies see the lookup and the key read a refusal skips.
        control = classify(client, ACCOUNT_A, _body())

    assert response.status_code == 400, response.text
    assert _detail_text(response) == "request body must be valid JSON"
    assert refused == ([], [], [], [])
    assert control.status_code == 200 and ENDPOINT_A in lookups and reads
    texts = [response.text, *messages_of(records), *(str(record.args) for record in records)]
    assert not [text for text in texts if MARKER in text or "RecursionError" in text]


def test_an_extra_field_is_named_in_the_refusal(byom: Harness) -> None:
    with started(byom, mixed_document()) as (client, _upstream):
        response = classify(client, ACCOUNT_A, _body(seed=7, top_k=2))

    detail = response.json()["detail"]
    assert detail["rejected"] == {"seed": "unknown", "top_k": "unknown"}


def test_an_ungranted_or_disabled_endpoint_is_answered_as_an_absent_one(byom: Harness) -> None:
    def ask(account: str, provider: str) -> tuple[int, str]:
        response = classify(client, account, _body(model=classifier_id(provider)))
        return response.status_code, response.text.replace(provider, UNREGISTERED)

    with started(byom, mixed_document(b_enabled=False)) as (client, upstream):
        absent = ask(ACCOUNT_A, UNREGISTERED)
        disabled = ask(ACCOUNT_A, ENDPOINT_B)
        ungranted = ask(ACCOUNT_B, ENDPOINT_B)

    assert disabled == ungranted == absent
    assert upstream.calls == []


def test_an_explicit_selector_is_refused_before_any_key_read(byom: Harness) -> None:
    with started(byom, mixed_document()) as (client, upstream):
        _attach(client, byom, (ACCOUNT_A, ENDPOINT_A))
        reads = key_reads(byom.monkeypatch)
        response = client.post(
            "/v1/classifications",
            json=_body(),
            headers={**tenant_headers(ACCOUNT_A), "X-Profile": "default"},
        )

    assert response.status_code == 400, response.text
    assert (reads, upstream.calls) == ([], [])


def test_a_pair_without_a_key_gets_the_chat_route_s_not_connected_refusal(byom: Harness) -> None:
    with started(byom, mixed_document()) as (client, upstream):
        classified = classify(client, ACCOUNT_A, classification_body(ENDPOINT_B, TEXT))
        chatted = chat(client, ACCOUNT_A, ENDPOINT_B)

    assert classified.status_code in (404, 409), classified.text
    assert (classified.status_code, classified.json()["detail"]) == (
        chatted.status_code,
        chatted.json()["detail"],
    )
    assert (upstream.calls, byom.upstream.calls) == ([], [])


def _echo_reply(request: httpx.Request) -> httpx.Response:
    text = json.loads(request.content)["inputs"]
    label = f"{request.url}|{request.headers['authorization']}|{text}"
    return httpx.Response(200, json=[[{"label": label, "score": 1.0}]])


def test_overlapping_classifications_never_cross(byom: Harness) -> None:
    calls = [(pair, f"text {n} of {pair[0][:4]} on {pair[1][-4:]}") for pair in KEY for n in (1, 2)]

    with started(byom, mixed_document()) as (client, upstream):
        _attach(client, byom)
        upstream.reply = _echo_reply
        upstream.expect_overlap(len(calls))

        async def overlap() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=client.app, client=PEER)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                requests = [
                    http.post(
                        "/v1/classifications",
                        json=classification_body(provider, text),
                        headers=tenant_headers(account),
                    )
                    for (account, provider), text in calls
                ]
                return list(await asyncio.gather(*requests))

        assert client.portal is not None
        responses = client.portal.call(overlap)

    labels = [response.json()["scores"][0]["label"] for response in responses]
    assert labels == [
        f"{URL[provider]}|Bearer {KEY[(account, provider)]}|{text}"
        for (account, provider), text in calls
    ]


def test_the_global_cache_is_neither_read_nor_written(
    byom: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    with started(byom, mixed_document()) as (client, upstream):
        _attach(client, byom, (ACCOUNT_A, ENDPOINT_A))
        store = cast(FastAPI, client.app).state.request_cache_store
        touched: list[str] = []
        for name in ("get", "set_if_absent"):
            original = getattr(store, name)

            async def spy(*args: Any, _name: str = name, _original: Any = original) -> Any:
                touched.append(_name)
                return await _original(*args)

            monkeypatch.setattr(store, name, spy)
        twice = [classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, TEXT)) for _ in "ab"]
        classified = list(touched)
        chatted = client.post(
            "/v1/chat/completions", json=chat_body(ENDPOINT_A), headers=tenant_headers(ACCOUNT_A)
        )

    assert [response.status_code for response in twice] == [200, 200]
    assert len(upstream.calls) == 2
    assert all("x-aigw-cache" not in response.headers for response in twice)
    assert classified == []
    # WHY: proves the spy sees the store reads a classification never makes.
    assert chatted.status_code == 200 and "get" in touched


def test_the_route_imports_no_chat_module() -> None:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(classifications))):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert not {name for name in imported if name.split(".")[-1].startswith("chat")}
