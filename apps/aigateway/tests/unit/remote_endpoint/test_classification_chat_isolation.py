"""Chat stays chat: a classifier target never becomes a chat model.

# FEATURE: hosted BYOM Unit 3 — a classifier shares its endpoint, grant and Connection with chat
# targets, but every chat surface sees the chat targets only.
# INVARIANT: a chat call naming a classifier is refused as an unknown alias is, before any key read
# and without upstream I/O.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .classifier_upstream import classifier_id, key_reads, mixed_document, started
from .conftest import Harness, chat, put_key, tenant_headers
from .fixtures import ACCOUNT_A, ALIAS, CLASSIFIER_ALIAS, ENDPOINT_A, ENDPOINT_B

KEY = "sk-byom-chat-isolation-0001"
# An alias no target declares: the reference answer for "not a chat model".
UNDECLARED = "undeclared_v1"


def _get(client: TestClient, path: str, **params: str) -> httpx.Response:
    return client.get(path, params=params, headers=tenant_headers(ACCOUNT_A))


def _admit(client: TestClient, model: str) -> httpx.Response:
    return client.post(
        "/v1/models/admit", json={"model_id": model}, headers=tenant_headers(ACCOUNT_A)
    )


def _as_undeclared(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.text.replace(CLASSIFIER_ALIAS, UNDECLARED)


def test_the_model_listing_shows_chat_targets_only(byom: Harness) -> None:
    with started(byom, mixed_document()) as (client, upstream):
        models = _get(client, "/v1/models")

    assert models.status_code == 200, models.text
    ids = {row["id"] for row in models.json()["data"]}
    assert {f"{ENDPOINT_A}/{ALIAS}", f"{ENDPOINT_B}/{ALIAS}"} <= ids
    assert not {classifier_id(ENDPOINT_A), classifier_id(ENDPOINT_B)} & ids
    assert upstream.calls == []


@pytest.mark.parametrize("surface", ["parameters", "admission"])
def test_a_classifier_id_is_answered_as_an_undeclared_chat_model(
    byom: Harness, surface: str
) -> None:
    def ask(client: TestClient, alias: str) -> httpx.Response:
        model = f"{ENDPOINT_A}/{alias}"
        if surface == "parameters":
            return _get(client, "/v1/model-parameters", model=model)
        return _admit(client, model)

    with started(byom, mixed_document()) as (client, upstream):
        classifier = ask(client, CLASSIFIER_ALIAS)
        undeclared = ask(client, UNDECLARED)

    assert _as_undeclared(classifier) == (undeclared.status_code, undeclared.text)
    if surface == "parameters":
        assert classifier.json()["detail"]["code"] == "model_not_found"
    else:
        assert classifier.json()["admitted"] is False
    assert upstream.calls == []


def test_a_chat_call_naming_a_classifier_is_refused_before_any_key_read(
    byom: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with started(byom, mixed_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        byom.upstream.calls.clear()
        reads = key_reads(monkeypatch)
        response = chat(client, ACCOUNT_A, ENDPOINT_A, CLASSIFIER_ALIAS)

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "invalid_model"
    assert (reads, byom.upstream.calls, upstream.calls) == ([], [], [])


def test_a_chat_call_naming_the_chat_target_still_serves(byom: Harness) -> None:
    with started(byom, mixed_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        response = chat(client, ACCOUNT_A, ENDPOINT_A)

    assert response.status_code == 200, response.text
    assert upstream.calls == []


def test_the_global_cache_never_takes_part_for_a_classifier_id() -> None:
    definition = parse_remote_endpoint_config(mixed_document()).endpoints[0]
    plugin = RemoteEndpointPlugin(definition)

    assert plugin.participates_in_global_cache(f"{ENDPOINT_A}/{ALIAS}") is True
    assert plugin.participates_in_global_cache(classifier_id(ENDPOINT_A)) is False
