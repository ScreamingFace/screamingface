"""A stored key is bound to the origin it was validated on; the same ID elsewhere sends nothing.

# FEATURE: hosted BYOM — endpoint IDs are durable credential identities. The plan forbids binding an
# old key to another destination when an endpoint is retargeted, or removed and later recreated.
# INVARIANT: a key leaves the gateway only for the origin recorded beside it in its encrypted blob;
# a key serves a new origin only after the normal replacement validated it there.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from aigateway.core.errors import AuthError, CredentialNotFoundError
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .conftest import Harness, chat, delete_pair, echo_of, put_key
from .fixtures import (
    ACCOUNT_A,
    CHAT_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
    document,
    endpoint,
    two_endpoint_document,
)

KEY = "sk-alice-on-a-bound-0001"
NEW_KEY = "sk-alice-on-a-bound-0002"
MOVED = "https://endpoint-a-moved.byom.test"


class _Blobs:
    """One in-memory credential blob."""

    def __init__(self, value: str | None = None) -> None:
        self.value = value

    async def read(self, service: str, account: str) -> str | None:
        return self.value

    async def write(self, service: str, account: str, value: str) -> None:
        self.value = value

    async def delete(self, service: str, account: str) -> None:
        self.value = None

    async def mutate(
        self, service: str, account: str, mutator: Callable[[str | None], str | None]
    ) -> None:
        self.value = mutator(self.value)


def _plugin_a() -> RemoteEndpointPlugin:
    return RemoteEndpointPlugin(parse_remote_endpoint_config(two_endpoint_document()).endpoints[0])


def _moved() -> dict[str, Any]:
    return document(endpoint(ENDPOINT_A, origin=MOVED), endpoint(ENDPOINT_B, origin=ORIGIN_B))


@pytest.mark.asyncio
async def test_a_persisted_key_records_the_origin_it_is_bound_to() -> None:
    blobs = _Blobs()
    strategy = _plugin_a().api_key_strategy_for("n", credential_store=blobs)

    await strategy.persist_credentials({"auth_type": "api_key", "api_key": KEY})

    assert blobs.value is not None
    assert json.loads(blobs.value) == {"auth_type": "api_key", "api_key": KEY, "origin": ORIGIN_A}
    assert await strategy.get_authorization_header() == {"Authorization": f"Bearer {KEY}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin", [MOVED, None, "", ORIGIN_A + "/"], ids=["moved", "null", "empty", "not-canonical"]
)
async def test_a_key_bound_to_another_origin_or_to_none_is_treated_as_missing(origin: Any) -> None:
    blob = {"auth_type": "api_key", "api_key": KEY, "origin": origin}
    strategy = _plugin_a().api_key_strategy_for("n", credential_store=_Blobs(json.dumps(blob)))

    for use in (strategy.get_authorization_header, strategy.refresh_credentials):
        with pytest.raises(CredentialNotFoundError) as caught:
            await use()
        # INVARIANT: the configured origins are private; the refusal names neither of them.
        assert MOVED not in str(caught.value) and ORIGIN_A not in str(caught.value)


@pytest.mark.asyncio
async def test_a_key_stored_without_an_origin_is_treated_as_missing() -> None:
    blob = json.dumps({"auth_type": "api_key", "api_key": KEY})
    strategy = _plugin_a().api_key_strategy_for("n", credential_store=_Blobs(blob))

    with pytest.raises(CredentialNotFoundError):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        None,
        "{not json",
        "[]",
        json.dumps({"auth_type": "oauth", "api_key": KEY, "origin": ORIGIN_A}),
        json.dumps({"auth_type": "api_key", "origin": ORIGIN_A}),
        json.dumps({"auth_type": "api_key", "api_key": "", "origin": ORIGIN_A}),
    ],
    ids=["absent", "not-json", "not-an-object", "not-an-api-key", "no-key", "empty-key"],
)
async def test_an_unusable_blob_is_treated_as_missing(raw: str | None) -> None:
    strategy = _plugin_a().api_key_strategy_for("n", credential_store=_Blobs(raw))

    with pytest.raises(CredentialNotFoundError):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "credentials", [{}, {"api_key": ""}, {"api_key": 7}], ids=["absent", "empty", "not-text"]
)
async def test_persisting_without_a_key_writes_nothing(credentials: dict[str, Any]) -> None:
    blobs = _Blobs()
    strategy = _plugin_a().api_key_strategy_for("n", credential_store=blobs)

    with pytest.raises(AuthError):
        await strategy.persist_credentials(credentials)

    assert blobs.value is None


def _refusal(response: httpx.Response) -> tuple[int, str]:
    assert MOVED not in response.text and ORIGIN_A not in response.text
    return response.status_code, response.json()["detail"]["code"]


def test_the_same_id_at_a_new_origin_sends_nothing_until_the_origin_returns(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
    byom.upstream.calls.clear()

    with byom.start(_moved()) as client:
        moved = chat(client, ACCOUNT_A, ENDPOINT_A)
    sent_while_moved = list(byom.upstream.calls)
    with byom.start(two_endpoint_document()) as client:
        restored = echo_of(chat(client, ACCOUNT_A, ENDPOINT_A))

    assert _refusal(moved) == (401, "auth_required")
    assert sent_while_moved == []
    # WHY the key survives: the move refused it without rewriting it, so the original origin
    # serves again — and only that origin.
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) == KEY
    assert restored == f"{ORIGIN_A}{CHAT_PATH}|Bearer {KEY}"


def test_after_a_move_a_replacement_is_validated_on_the_new_origin_and_then_serves(
    byom: Harness,
) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
    byom.upstream.calls.clear()

    with byom.start(_moved()) as client:
        replaced = put_key(client, ACCOUNT_A, ENDPOINT_A, NEW_KEY)
        served = echo_of(chat(client, ACCOUNT_A, ENDPOINT_A))

    assert replaced.status_code == 200, replaced.text
    assert [(c.url, c.bearer, c.probe) for c in byom.upstream.calls] == [
        (MOVED + CHAT_PATH, f"Bearer {NEW_KEY}", True),
        (MOVED + CHAT_PATH, f"Bearer {NEW_KEY}", False),
    ]
    assert served == f"{MOVED}{CHAT_PATH}|Bearer {NEW_KEY}"


def test_after_a_move_the_admin_can_still_delete_the_pair(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200

    with byom.start(_moved()) as client:
        deleted = delete_pair(client, ACCOUNT_A, ENDPOINT_A)

    assert deleted.status_code == 204, deleted.text
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) is None


def test_removing_the_id_and_adding_it_back_elsewhere_sends_nothing(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
    with byom.start(document(endpoint(ENDPOINT_B, origin=ORIGIN_B))):
        pass
    byom.upstream.calls.clear()

    with byom.start(_moved()) as client:
        recreated = chat(client, ACCOUNT_A, ENDPOINT_A)

    assert _refusal(recreated) == (401, "auth_required")
    assert byom.upstream.calls == []
