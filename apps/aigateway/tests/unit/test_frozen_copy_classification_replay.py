"""C9 classification replay reads one sealed store entry and performs no live provider work."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.models import STATUS_ABANDONED, STATUS_EXPIRED, FrozenCopy
from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata
from aigateway.plugins.taxonomy import (
    DirectCost,
    InputTokenUsage,
    OutputTokenUsage,
    TokenUsage,
    cache_reference_from_entry_metadata,
)
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from tests.unit.test_frozen_copy_support import (
    ATTEMPT_HEADER,
    BINDING_HEADER,
    CASE_A,
    CASE_KEY_HEADER,
    OCCURRENCE_HEADER,
    account_id_of,
    classification_body,
    classification_call_key,
    run_async,
    seed_classification_copy,
)

_ATTEMPTS = "X-AIGW-Upstream-Attempts"
_REPLAY = "X-AIGW-Replay"
_BAD_BINDINGS = ("router_0", "router_01", "router_+1", "router_ 1", "router_١")


def _path(copy_id: str) -> str:
    return f"/v1/frozen-copies/{copy_id}/classifications"


def _result(marker: str, aigw: Any = None) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "model": "hf-inference/sentiment",
        "scores": [{"label": marker, "score": 1.0}],
    }
    if aigw is not None:
        answer["_aigw"] = aigw
    return answer


def _priced_reference(amount: str) -> dict[str, Any]:
    metadata = CacheEntryMetadata(
        metadata_status="complete",
        observed_at="2026-11-27T00:00:00Z",
        response_model="hf-inference/sentiment",
        usage=TokenUsage(
            status="complete",
            source="provider_raw_response",
            input=InputTokenUsage(total=4, uncached=4),
            output=OutputTokenUsage(total=1),
        ).as_json(),
        direct_cost=DirectCost.reported(
            amount=amount, unit="openrouter_credits", source="openrouter.usage.cost"
        ).as_json(),
        provider_latency_ms=12,
    )
    return render_aigw_metadata(
        collector=None,
        supported=True,
        cache_status="hit",
        gateway_call_id="call_" + "a" * 32,
        cache_reference=cache_reference_from_entry_metadata(metadata),
    )


def _seed(
    client: TestClient,
    response: dict[str, Any],
    *,
    status: int = 200,
    body: dict[str, Any] | None = None,
    binding: str = "router_1",
    attempt: int | None = None,
    seal: bool = True,
) -> str:
    return seed_classification_copy(
        client,
        account_id_of(client),
        [
            (
                CASE_A,
                0,
                binding,
                attempt,
                classification_body() if body is None else body,
                response,
                status,
            )
        ],
        seal=seal,
    )


@pytest.mark.parametrize(
    ("captured", "expected_amount"),
    [
        (None, None),
        ({"usage_accounting": "malformed"}, None),
        (_priced_reference("0"), "0"),
        (_priced_reference("0.25"), "0.25"),
    ],
    ids=["absent", "malformed", "measured-zero", "positive"],
)
def test_success_replay_preserves_fields_and_adds_only_replay_accounting(
    authenticated_client: TestClient,
    captured: Any,
    expected_amount: str | None,
) -> None:
    client = authenticated_client
    stored = _result("positive", captured)
    copy_id = _seed(client, stored)

    response = client.post(
        _path(copy_id), json=classification_body(), headers=classification_call_key(CASE_A)
    )

    assert response.status_code == 200, response.text
    assert response.headers[_REPLAY] == "hit"
    assert response.headers[_ATTEMPTS] == "0"
    assert response.json()["model"] == stored["model"]
    assert response.json()["scores"] == stored["scores"]
    aigw = response.json()["_aigw"]
    assert aigw["frozen_copy_replay"] is True
    assert aigw["usage_accounting"]["cache"]["status"] == "hit"
    assert aigw["usage_accounting"]["observed_attempts"] == 0
    assert aigw["request_economics"]["observed_new_attempts"] == 0
    assert aigw["request_economics"]["direct_cost_status"] == "not_applicable"
    reference = aigw["usage_accounting"]["cache"]["reference"]
    if expected_amount is None:
        assert reference is None
    else:
        assert reference["direct_cost"]["amount"] == expected_amount


def test_recorded_error_preserves_detail_status_header_and_has_no_price_reference(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    detail = {"code": "provider_error", "message": "temporarily unavailable"}
    stored = {
        "detail": detail,
        "headers": {"Retry-After": "7"},
        "_aigw": _priced_reference("9"),
    }
    copy_id = _seed(client, stored, status=429)

    response = client.post(
        _path(copy_id), json=classification_body(), headers=classification_call_key(CASE_A)
    )

    assert response.status_code == 429
    assert response.json()["detail"] == detail
    assert response.headers["Retry-After"] == "7"
    assert response.headers[_REPLAY] == "error"
    assert response.headers[_ATTEMPTS] == "0"
    aigw = response.json()["_aigw"]
    assert aigw["frozen_copy_replay"] is True
    assert aigw["usage_accounting"]["cache"]["reference"] is None
    assert aigw["request_economics"]["direct_cost_status"] == "not_applicable"


def test_route_forwards_binding_occurrence_and_attempt_to_the_store(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    body = classification_body()
    copy_id = seed_classification_copy(
        client,
        account_id_of(client),
        [
            (CASE_A, 0, "router_1", None, body, _result("binding-1"), 200),
            (CASE_A, 0, "router_2", None, body, _result("binding-2"), 200),
            (CASE_A, 1, "router_1", None, body, _result("occurrence-1"), 200),
            (CASE_A, 0, "router_1", 2, body, _result("attempt-2"), 200),
        ],
    )

    def replay(binding: str, occurrence: int, attempt: int | None) -> str:
        response = client.post(
            _path(copy_id),
            json=body,
            headers=classification_call_key(CASE_A, occurrence, binding, attempt),
        )
        assert response.status_code == 200, response.text
        return response.json()["scores"][0]["label"]

    assert replay("router_1", 0, None) == "binding-1"
    assert replay("router_2", 0, None) == "binding-2"
    assert replay("router_1", 1, None) == "occurrence-1"
    assert replay("router_1", 0, 2) == "attempt-2"


class _Forbidden:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"classification replay touched {name}")


def test_replay_never_resolves_provider_connection_credential_plugin_or_cache(
    authenticated_client: TestClient, monkeypatch
) -> None:
    from aigateway.core.provider_access.connection_backed import ConnectionBackedProviderAccess
    from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

    async def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("classification replay reached a live collaborator")

    monkeypatch.setattr(ConnectionBackedProviderAccess, "resolve", forbidden)
    monkeypatch.setattr(ConnectionBackedProviderAccess, "authorize", forbidden)
    monkeypatch.setattr(RemoteEndpointPlugin, "classify", forbidden)
    monkeypatch.setattr(
        cast(Any, authenticated_client.app).state, "request_cache_store", _Forbidden()
    )
    body = classification_body(model="retired/removed-classifier")
    copy_id = _seed(authenticated_client, _result("stored"), body=body)

    response = authenticated_client.post(
        _path(copy_id), json=body, headers=classification_call_key(CASE_A)
    )

    assert response.status_code == 200, response.text
    assert response.json()["scores"][0]["label"] == "stored"


def test_any_authenticated_account_holding_the_id_may_replay(
    authenticated_client: TestClient, provisioned_user_factory
) -> None:
    copy_id = _seed(authenticated_client, _result("stored"))
    provisioned_user_factory("replayer")
    login = authenticated_client.post(
        "/v1/auth/login", json={"username": "replayer", "password": "test-user-password"}
    )
    auth = {"Authorization": f"Bearer {login.json()['token']}"}

    response = authenticated_client.post(
        _path(copy_id),
        json=classification_body(),
        headers=auth | classification_call_key(CASE_A),
    )

    assert response.status_code == 200, response.text


def test_replay_requires_authentication(client: TestClient) -> None:
    response = client.post(
        _path(str(uuid4())), json=classification_body(), headers=classification_call_key(CASE_A)
    )

    assert response.status_code in (401, 403)


@pytest.mark.parametrize("status", ["open", STATUS_ABANDONED, STATUS_EXPIRED])
def test_nonsealed_current_states_are_the_shared_unavailable_404(
    authenticated_client: TestClient, status: str
) -> None:
    client = authenticated_client
    copy_id = _seed(client, _result("stored"), seal=status != "open")

    if status != "open":

        async def set_status() -> None:
            await FrozenCopy.filter(id=UUID(copy_id)).update(status=status)

        run_async(client, set_status)

    response = client.post(
        _path(copy_id), json=classification_body(), headers=classification_call_key(CASE_A)
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "frozen_copy_unavailable"
    assert _REPLAY not in response.headers


def test_unknown_and_malformed_copy_ids_are_the_shared_unavailable_404(
    authenticated_client: TestClient,
) -> None:
    for copy_id in (str(uuid4()), "not-a-uuid"):
        response = authenticated_client.post(
            _path(copy_id), json=classification_body(), headers=classification_call_key(CASE_A)
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "frozen_copy_unavailable"


@pytest.mark.parametrize(
    "headers",
    [
        {CASE_KEY_HEADER: CASE_A, OCCURRENCE_HEADER: "0"},
        *[
            classification_call_key(CASE_A) | {BINDING_HEADER: binding}
            for binding in _BAD_BINDINGS
            if binding.isascii()
        ],
        classification_call_key(CASE_A) | {BINDING_HEADER: "router_x"},
        classification_call_key(CASE_A) | {ATTEMPT_HEADER: "1"},
    ],
)
def test_bad_or_missing_classification_key_is_malformed_before_copy_lookup(
    authenticated_client: TestClient, monkeypatch, headers: dict[str, str]
) -> None:
    async def forbidden_get(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("bad call key reached the store")

    monkeypatch.setattr("aigateway.core.frozen_copy.store.FrozenCopyStore.get", forbidden_get)

    response = authenticated_client.post(
        _path(str(uuid4())), json=classification_body(), headers=headers
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "malformed_call_key"


@pytest.mark.parametrize("binding", _BAD_BINDINGS)
def test_route_adapter_maps_every_noncanonical_binding_to_malformed_call_key(
    binding: str,
) -> None:
    from aigateway.routes.frozen_copies import _classification_call_key

    request = cast(
        Request,
        SimpleNamespace(headers=classification_call_key(CASE_A) | {BINDING_HEADER: binding}),
    )

    with pytest.raises(HTTPException) as raised:
        _classification_call_key(request)

    assert raised.value.status_code == 400
    detail: Any = raised.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "malformed_call_key"


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"model": "m", "input": "x", "extra": 1},
        {"model": 1, "input": "x"},
        {"model": "m", "input": ["x"]},
        {
            "model": "m",
            "input": {
                "contract": "classification-choice-input-v1",
                "text": "question",
                "instructions": "choose",
                "options": [],
            },
        },
    ],
)
def test_replay_body_is_the_strict_two_field_classification_request(
    authenticated_client: TestClient, body: Any
) -> None:
    copy_id = _seed(authenticated_client, _result("stored"))

    response = authenticated_client.post(
        _path(copy_id), json=body, headers=classification_call_key(CASE_A)
    )

    assert response.status_code == 400


def test_choice_input_replays_without_provider_validation(authenticated_client: TestClient) -> None:
    choice = {
        "contract": "classification-choice-input-v1",
        "text": "Which answer is correct?",
        "instructions": "Choose one.",
        "options": [
            {"label": "a", "description": "first"},
            {"label": "b", "description": "second"},
        ],
    }
    body = classification_body(input=choice)
    copy_id = _seed(authenticated_client, _result("b"), body=body)

    response = authenticated_client.post(
        _path(copy_id), json=body, headers=classification_call_key(CASE_A)
    )

    assert response.status_code == 200, response.text
    assert response.json()["scores"][0]["label"] == "b"


def test_uncaptured_request_is_a_miss(authenticated_client: TestClient) -> None:
    copy_id = _seed(authenticated_client, _result("stored"))

    response = authenticated_client.post(
        _path(copy_id),
        json=classification_body(input="different"),
        headers=classification_call_key(CASE_A),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "frozen_copy_miss"
