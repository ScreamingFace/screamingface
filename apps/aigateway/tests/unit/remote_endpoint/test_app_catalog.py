"""The grant-filtered catalog: who finds a configured endpoint, and what everyone else gets.

# FEATURE: hosted BYOM Unit 1 — a granted account finds its endpoints in the model and provider
# listings, in provider availability and in the model contract.
# STORY: as a tenant granted an endpoint, I find its model in `/v1/models` and read its parameter
# contract before I chat; another tenant does not find it in the working catalog. Published
# community-cache entries still name it to every account, on purpose
# (`test_app_shared_cache.py`).
# INVARIANT: an ungranted account and a disabled endpoint get exactly the answer each route gives
# for a provider that is not registered, and no catalog surface reaches the upstream.
# INVARIANT: no catalog answer names an origin, a request path or an upstream model.
# INVARIANT: an availability row is a registered provider the caller may see. A stored pair of any
# other provider stays stored, is never read for a status and gets no row.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.oauth.store import OAuthConnectionStore

from .conftest import Harness, put_key, tenant_headers
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
    document,
    endpoint,
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


B_KEY = "sk-alice-on-b-0001"


def _availability(client: TestClient, account: str) -> dict[str, str]:
    response = _get(client, account, "/v1/provider-access")
    assert response.status_code == 200, response.text
    return {row["provider"]: row["status"] for row in response.json()["providers"]}


def _connect_a_to_b(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_B, B_KEY).status_code == 200
        assert _availability(client, ACCOUNT_A)[ENDPOINT_B] == "connected"


@pytest.mark.parametrize(
    "later",
    [document(endpoint(ENDPOINT_A)), None],
    ids=["endpoint removed from the config", "config removed"],
)
def test_a_pair_of_an_unregistered_endpoint_gets_no_availability_row(
    byom: Harness, later: dict[str, Any] | None
) -> None:
    _connect_a_to_b(byom)

    with byom.start(later) as client:
        rows = _availability(client, ACCOUNT_A)

    assert ENDPOINT_B not in rows
    # WHY: hiding the row deletes nothing; the account still owns its pair and may remove it.
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_B) == B_KEY


@pytest.mark.parametrize(
    "later",
    [two_endpoint_document(b_enabled=False), two_endpoint_document(b_accounts=(ACCOUNT_B,))],
    ids=["endpoint disabled", "grant withdrawn"],
)
def test_a_hidden_pair_is_never_read_for_the_availability_listing(
    byom: Harness, later: dict[str, Any]
) -> None:
    _connect_a_to_b(byom)

    async def unreadable(service: str, account: str) -> None:
        raise RuntimeError("credential state unavailable")

    with byom.start(later) as client:
        store = cast(FastAPI, client.app).state.credential_store
        # WHY a failing read: a listing that still read the hidden pair would answer 503.
        byom.monkeypatch.setattr(store, "operational_state", unreadable)
        rows = _availability(client, ACCOUNT_A)

    assert ENDPOINT_B not in rows


@pytest.mark.parametrize(
    "later",
    [two_endpoint_document(b_enabled=False), two_endpoint_document(b_accounts=(ACCOUNT_B,))],
    ids=["endpoint disabled", "grant withdrawn"],
)
def test_a_hidden_pair_s_connection_is_never_read_for_the_availability_listing(
    byom: Harness, later: dict[str, Any]
) -> None:
    _connect_a_to_b(byom)

    async def unreadable(self: OAuthConnectionStore, account_id: str, connection_id: str) -> None:
        raise RuntimeError("connection unavailable")

    with byom.start(later) as client:
        # WHY a failing read: a listing that read the hidden pair's Connection would fail.
        byom.monkeypatch.setattr(OAuthConnectionStore, "get", unreadable)
        rows = _availability(client, ACCOUNT_A)

    assert ENDPOINT_B not in rows


# --- the contract the SDK preflight reads (OME-1770) --------------------------------------------


def test_the_contract_reads_missing_until_that_account_attaches_a_key(byom: Harness) -> None:
    """FEATURE: hosted BYOM Unit 2. The SDK stops a `missing` model before dispatch and runs a
    `configured` one, so a granted account without a key must read `missing`, and only the
    account whose key is attached reads `configured`."""
    with byom.start(two_endpoint_document()) as client:
        before = _get(client, ACCOUNT_A, "/v1/model-parameters", model=_model(ENDPOINT_A))
        attached = put_key(client, ACCOUNT_A, ENDPOINT_A, "sk-alice-on-a-contract-0001")
        after = _get(client, ACCOUNT_A, "/v1/model-parameters", model=_model(ENDPOINT_A))
        other = _get(client, ACCOUNT_B, "/v1/model-parameters", model=_model(ENDPOINT_A))

    assert attached.status_code == 200, attached.text
    assert [r.status_code for r in (before, after, other)] == [200, 200, 200]
    assert before.json()["context"]["execution_access"] == "missing"
    assert after.json()["context"]["execution_access"] == "configured"
    # INVARIANT: a Connection is per (account, endpoint) pair; A's key configures no one else.
    assert other.json()["context"]["execution_access"] == "missing"
    _assert_private([before, after, other])


def test_the_contract_publishes_no_seed_row(byom: Harness) -> None:
    """WHY: with no `seed` row the SDK refuses a seeded evaluation before any spend; the chat
    route refuses a seed too (`test_request_contract.py`)."""
    with byom.start(two_endpoint_document()) as client:
        contract = _get(client, ACCOUNT_A, "/v1/model-parameters", model=_model(ENDPOINT_A))

    assert contract.status_code == 200, contract.text
    assert set(contract.json()["parameters"]) == {"max_tokens"}
