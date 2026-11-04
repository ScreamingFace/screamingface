"""The Local Engine lists the Connection chat uses (OME-1138 close-out, L7b).

FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §3 — the Local adapter selects
the row the gateway flags `effective` (`E`), takes every status from `GET /v1/provider-access`,
and refuses a listing that breaks the contract. `A` is the number of the provider's `active` rows.
The writes are in `test_connections_aigateway_effective_writes.py`.
STORY: as a Local Engine user, the connection I see and manage is the one chat uses.
"""

from __future__ import annotations

import httpx
import pytest
from aigateway_effective_support import (
    ABSENT,
    ACCESS_PATH,
    BOTH,
    OTHER_ID,
    ROWS_PATH,
    SECRET,
    Gateway,
    row,
)

from screamingface_engine.connections.port import (
    Caller,
    Connection,
    ConnectionBadResponse,
    ConnectionStatus,
    ConnectionTimeout,
    ConnectionUnavailable,
)

pytestmark = pytest.mark.asyncio


# --- list: the status from provider access, the method and account from E ----------------------


@pytest.mark.parametrize("status", ["connected", "needs_reauth", "error"])
async def test_list_shows_the_provider_access_status_of_an_active_effective_row(
    status: ConnectionStatus,
) -> None:
    gateway = Gateway(row(effective=True), access={"openrouter": status})

    (connection,) = await gateway.adapter().list(Caller())

    # WHY: an `active` row is not necessarily `connected` — a recorded API-key outcome lists
    # `needs_reauth`, `insufficient_credits` lists `error`; the Engine never derives a status.
    assert connection == Connection(
        "openrouter", "OpenRouter", ("api_key",), status, auth_method="api_key"
    )
    assert gateway.calls() == ["GET /v1/providers", f"GET {ROWS_PATH}", f"GET {ACCESS_PATH}"]


async def test_an_effective_oauth_row_adds_its_safe_account_label() -> None:
    oauth_row = row(
        provider="anthropic",
        auth_type="oauth",
        label="work",
        account={"email": " alice@example.com ", "raw": {"access_token": "must-not-leak"}},
        effective=True,
    )
    gateway = Gateway(oauth_row, providers=(BOTH,), access={"anthropic": "connected"})

    (connection,) = await gateway.adapter().list(Caller())

    assert connection.auth_method == "oauth"
    assert connection.account_label == "alice@example.com"
    assert "must-not-leak" not in repr(connection)


async def test_a_provider_absent_from_provider_access_lists_not_connected() -> None:
    gateway = Gateway(access={})

    assert await gateway.adapter().list(Caller()) == (
        Connection("openrouter", "OpenRouter", ("api_key",), "not_connected"),
    )


async def test_two_active_rows_with_none_effective_list_the_status_alone() -> None:
    gateway = Gateway(row(label="one"), row(OTHER_ID, label="two"), access={"openrouter": "error"})

    assert await gateway.adapter().list(Caller()) == (
        Connection("openrouter", "OpenRouter", ("api_key",), "error"),
    )


# --- the listing checks ------------------------------------------------------------------------


async def test_the_field_on_some_rows_only_is_a_bad_response() -> None:
    unlisted = row(OTHER_ID, provider="ollama", effective=ABSENT)
    gateway = Gateway(row(effective=True), unlisted, access={"openrouter": "connected"})

    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().list(Caller())


async def test_two_flagged_rows_of_a_listed_provider_are_a_bad_response() -> None:
    gateway = Gateway(row(effective=True), row(OTHER_ID, label="research", effective=True))

    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().list(Caller())


async def test_one_active_row_and_none_flagged_is_a_bad_response_before_any_write() -> None:
    gateway = Gateway(row(label="research"))

    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().list(Caller())
    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().connect(Caller(), "openrouter", SECRET)

    assert gateway.writes() == []
    assert all(SECRET not in request.content.decode() for request in gateway.requests)


@pytest.mark.parametrize("flag", [None, "true", 1])
async def test_an_effective_flag_that_is_not_a_boolean_is_a_bad_response(flag: object) -> None:
    gateway = Gateway(row(effective=flag))

    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().list(Caller())


async def test_an_effective_row_of_a_method_the_provider_lacks_is_a_bad_response() -> None:
    # INVARIANT: `E` supplies `auth_method`, which must be one the catalogue lists for it.
    gateway = Gateway(row(auth_type="oauth", effective=True), access={"openrouter": "connected"})

    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().list(Caller())


async def test_a_stray_active_row_of_an_unlisted_provider_is_ignored() -> None:
    # INVARIANT (spec §3, §6.3): a no-auth provider has no effective row; `/v1/providers` does
    # not list it, so the Engine never selects, checks or builds anything from its rows.
    stray = row(OTHER_ID, provider="ollama", auth_type="oauth", label="local")
    gateway = Gateway(
        row(effective=True), stray, access={"openrouter": "needs_reauth", "ollama": "connected"}
    )

    assert await gateway.adapter().list(Caller()) == (
        Connection("openrouter", "OpenRouter", ("api_key",), "needs_reauth", auth_method="api_key"),
    )


# --- failures of the provider-access read ------------------------------------------------------


async def test_a_malformed_provider_access_body_is_a_bad_response() -> None:
    gateway = Gateway(row(effective=True))
    gateway.fail[f"GET {ACCESS_PATH}"] = httpx.Response(
        200, json={"providers": [{"provider": "openrouter", "status": "online"}]}
    )

    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().list(Caller())


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ConnectError("down"), ConnectionUnavailable),
        (httpx.ReadTimeout("slow"), ConnectionTimeout),
    ],
)
async def test_provider_access_transport_failures_are_typed(
    failure: Exception, expected: type[Exception]
) -> None:
    gateway = Gateway(row(effective=True))
    gateway.fail[f"GET {ACCESS_PATH}"] = failure

    with pytest.raises(expected):
        await gateway.adapter().list(Caller())
