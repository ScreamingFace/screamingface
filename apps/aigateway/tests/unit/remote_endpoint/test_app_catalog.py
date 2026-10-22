"""The grant-filtered catalog: who finds a configured endpoint, and what everyone else gets.

# FEATURE: hosted BYOM Unit 1 — a granted account finds its endpoints in the model and provider
# listings, in provider availability and in the model contract.
# STORY: as a tenant granted an endpoint, I find its model in `/v1/models` and read its parameter
# contract before I chat; another tenant cannot tell that the endpoint is configured.
# INVARIANT: an ungranted account and a disabled endpoint get exactly the answer each route gives
# for a provider that is not registered, and no catalog surface reaches the upstream.
# INVARIANT: no catalog answer names an origin, a request path or an upstream model.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .conftest import Harness, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ALIAS,
    CHAT_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
    UPSTREAM_MODEL,
    two_endpoint_document,
)

# An endpoint-shaped ID no config declares: the reference answer for "not registered".
UNREGISTERED = "byom_" + "c" * 32
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Authorization"}


def _model(provider: str) -> str:
    return f"{provider}/{ALIAS}"


def _get(client: TestClient, account: str, path: str, **params: str) -> httpx.Response:
    return client.get(path, params=params, headers=tenant_headers(account))


def _post(client: TestClient, account: str, path: str, body: dict[str, Any]) -> httpx.Response:
    return client.post(path, json=body, headers=tenant_headers(account))


def _ids(response: httpx.Response, key: str = "data", field: str = "id") -> set[str]:
    assert response.status_code == 200, response.text
    return {row[field] for row in response.json()[key]}


def _surfaces(client: TestClient, account: str) -> dict[str, set[str]]:
    """What one account finds in each listing, restricted to the configured endpoints."""
    endpoints = {ENDPOINT_A, ENDPOINT_B}
    models = _ids(_get(client, account, "/v1/models"))
    return {
        "models": {m for m in models if m.split("/", 1)[0] in endpoints},
        "providers": _ids(_get(client, account, "/v1/providers")) & endpoints,
        "availability": _ids(
            _get(client, account, "/v1/provider-access"), key="providers", field="provider"
        )
        & endpoints,
    }


def _as_unregistered(response: httpx.Response, provider: str) -> tuple[int, str]:
    """The response with the provider's ID swapped for the unregistered one."""
    return response.status_code, response.text.replace(provider, UNREGISTERED)


def _refusals(client: TestClient, account: str, provider: str) -> list[httpx.Response]:
    """Every catalog surface that looks one provider up, asked about ``provider``."""
    return [
        _get(client, account, "/v1/model-parameters", model=_model(provider)),
        _post(client, account, "/v1/models/admit", {"model_id": _model(provider)}),
        _post(client, account, "/v1/oauth/connections", {"provider": provider}),
    ]


def _assert_private(responses: list[httpx.Response]) -> None:
    for response in responses:
        text = response.text
        assert ORIGIN_A not in text and ORIGIN_B not in text
        assert CHAT_PATH not in text and UPSTREAM_MODEL not in text


def test_each_account_finds_exactly_the_endpoints_granted_to_it(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        seen = {account: _surfaces(client, account) for account in (ACCOUNT_A, ACCOUNT_B)}

    assert seen[ACCOUNT_A] == {
        "models": {_model(ENDPOINT_A), _model(ENDPOINT_B)},
        "providers": {ENDPOINT_A, ENDPOINT_B},
        "availability": {ENDPOINT_A, ENDPOINT_B},
    }
    assert seen[ACCOUNT_B] == {
        "models": {_model(ENDPOINT_A)},
        "providers": {ENDPOINT_A},
        "availability": {ENDPOINT_A},
    }
    assert byom.upstream.calls == []


def test_a_disabled_endpoint_is_found_by_nobody(byom: Harness) -> None:
    with byom.start(two_endpoint_document(b_enabled=False)) as client:
        seen = _surfaces(client, ACCOUNT_A)

    assert seen == {
        "models": {_model(ENDPOINT_A)},
        "providers": {ENDPOINT_A},
        "availability": {ENDPOINT_A},
    }


def test_a_granted_account_gets_the_rows_and_the_model_contract(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        models = _get(client, ACCOUNT_B, "/v1/models")
        providers = _get(client, ACCOUNT_B, "/v1/providers")
        availability = _get(client, ACCOUNT_B, "/v1/provider-access")
        contract = _get(client, ACCOUNT_B, "/v1/model-parameters", model=_model(ENDPOINT_A))
        admitted = _post(client, ACCOUNT_B, "/v1/models/admit", {"model_id": _model(ENDPOINT_A)})
        admitted_models = dict(cast(FastAPI, client.app).state.admitted_models)

    (row,) = [r for r in models.json()["data"] if r["owned_by"] == ENDPOINT_A]
    assert row["id"] == _model(ENDPOINT_A)
    assert row["parameter_contract_url"].startswith("/v1/model-parameters?model=")
    assert [r for r in providers.json()["data"] if r["id"] == ENDPOINT_A] == [
        {
            "object": "provider",
            "id": ENDPOINT_A,
            "display_name": "Lab endpoint aaaa",
            "auth_methods": ["api_key"],
        }
    ]
    assert {"provider": ENDPOINT_A, "status": "not_connected"} in availability.json()["providers"]
    assert contract.status_code == 200, contract.text
    assert contract.json()["model"]["id"] == _model(ENDPOINT_A)
    assert admitted.json()["admitted"] is True
    # INVARIANT: a declared target is already served; admission never stores an endpoint's
    # model in the deployment-wide admitted list, which every account's listing reads.
    assert admitted_models == {}
    _assert_private([models, providers, availability, contract, admitted])
    assert byom.upstream.calls == []


def test_an_ungranted_account_gets_the_unregistered_answer_everywhere(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        denied = _refusals(client, ACCOUNT_B, ENDPOINT_B)
        absent = _refusals(client, ACCOUNT_B, UNREGISTERED)
        undeclared = _post(
            client, ACCOUNT_B, "/v1/models/admit", {"model_id": f"{ENDPOINT_B}/other"}
        )
        absent_undeclared = _post(
            client, ACCOUNT_B, "/v1/models/admit", {"model_id": f"{UNREGISTERED}/other"}
        )

    assert [_as_unregistered(r, ENDPOINT_B) for r in denied] == [
        (r.status_code, r.text) for r in absent
    ]
    assert _as_unregistered(undeclared, ENDPOINT_B) == (
        absent_undeclared.status_code,
        absent_undeclared.text,
    )
    assert byom.upstream.calls == []


def test_a_disabled_endpoint_gets_the_unregistered_answer_even_when_granted(
    byom: Harness,
) -> None:
    with byom.start(two_endpoint_document(b_enabled=False)) as client:
        denied = _refusals(client, ACCOUNT_A, ENDPOINT_B)
        absent = _refusals(client, ACCOUNT_A, UNREGISTERED)

    assert [_as_unregistered(r, ENDPOINT_B) for r in denied] == [
        (r.status_code, r.text) for r in absent
    ]
    assert byom.upstream.calls == []


def test_the_granted_listings_are_private_to_the_caller(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        listings = [
            _get(client, ACCOUNT_A, "/v1/models"),
            _get(client, ACCOUNT_A, "/v1/providers"),
        ]

    for listing in listings:
        assert listing.status_code == 200
        # WHY: the rows now depend on the caller's grants, so no shared cache may keep them.
        assert {key: listing.headers.get(key) for key in PRIVATE} == PRIVATE
