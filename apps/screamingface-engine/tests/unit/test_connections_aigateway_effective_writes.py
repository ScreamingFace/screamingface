"""The Local Engine writes the Connection chat uses (OME-1138 close-out, L7b).

FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §3 — `connect`, `start_oauth`
and `disconnect` follow the create and repair table over the row the gateway flags `effective`
(`E`); `connect` and `disconnect` return the status `GET /v1/provider-access` lists after their
writes. `A` is the number of the provider's `active` rows. The listing is in
`test_connections_aigateway_effective.py`.
STORY: as a Local Engine user, the connection I see and manage is the one chat uses.
"""

from __future__ import annotations

import httpx
import pytest
from aigateway_effective_support import (
    ACCESS_PATH,
    BOTH,
    CREATED_ID,
    E_ID,
    OTHER_ID,
    ROWS_PATH,
    SECRET,
    THIRD_ID,
    Gateway,
    row,
    written,
)

from screamingface_engine.connections.port import (
    Caller,
    Connection,
    ConnectionAlreadyConnected,
    ConnectionBadResponse,
    ConnectionConflict,
    ConnectionStatus,
)

pytestmark = pytest.mark.asyncio


# --- connect -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("status", "label"), [("active", "screamingface"), ("error", "research")])
async def test_connect_rekeys_an_effective_api_key_row_in_place(status: str, label: str) -> None:
    gateway = Gateway(
        row(status=status, label=label, effective=True),
        access={"openrouter": "error"},
        access_after_write={"openrouter": "connected"},
    )

    connection = await gateway.adapter().connect(Caller(), "openrouter", SECRET)

    # WHY the user's label is accepted: an in-place PUT keeps the name the row already has.
    assert gateway.writes() == [f"PUT {ROWS_PATH}/{E_ID}/api-key"]
    assert gateway.bodies() == [{"api_key": SECRET}]
    assert connection.status == "connected" and connection.auth_method == "api_key"
    assert SECRET not in repr(connection)


@pytest.mark.parametrize(
    ("auth_type", "status"),
    [("oauth", "error"), ("oauth", "expired"), ("oauth", "revoked"), ("api_key", "revoked")],
)
async def test_connect_replaces_an_unusable_effective_row_with_a_labelled_create(
    auth_type: str, status: str
) -> None:
    effective = row(
        provider="anthropic", auth_type=auth_type, status=status, label="work", effective=True
    )
    gateway = Gateway(effective, providers=(BOTH,), access_after_write={"anthropic": "connected"})

    connection = await gateway.adapter().connect(Caller(), "anthropic", SECRET)

    # WHY nothing removed: no other row holds the label; the gateway's create replaces E itself.
    assert gateway.writes() == [f"POST {ROWS_PATH}/api-key"]
    assert gateway.bodies() == [
        {"provider": "anthropic", "label": "screamingface", "api_key": SECRET}
    ]
    assert connection.status == "connected"


@pytest.mark.parametrize(
    ("auth_type", "status"), [("oauth", "pending"), ("api_key", "error")], ids=["start", "key"]
)
@pytest.mark.parametrize("operation", ["connect", "start_oauth"])
async def test_a_stale_label_row_beside_an_unusable_effective_row_is_removed_first(
    operation: str, auth_type: str, status: str
) -> None:
    # WHY (owner, 2026-11-04): a pre-L7b Engine created its `screamingface` row beside a migrated
    # `E`; once `E` is unusable, that row would block the replacing create with `label_conflict`
    # on every attempt. It serves nothing, so the repair removes it first.
    effective = row(
        provider="anthropic", auth_type="oauth", status="expired", label="work", effective=True
    )
    stale = row(OTHER_ID, provider="anthropic", auth_type=auth_type, status=status)
    gateway = Gateway(
        effective, stale, providers=(BOTH,), access_after_write={"anthropic": "connected"}
    )
    adapter = gateway.adapter()

    if operation == "connect":
        await adapter.connect(Caller(), "anthropic", SECRET)
        create = f"POST {ROWS_PATH}/api-key"
    else:
        await adapter.start_oauth(Caller(), "anthropic")
        create = f"POST {ROWS_PATH}"

    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{OTHER_ID}", create]


@pytest.mark.parametrize("operation", ["connect", "start_oauth"])
async def test_an_active_label_row_beside_an_unusable_effective_row_is_a_conflict(
    operation: str,
) -> None:
    # WHY (owner, 2026-11-04): the gateway refuses a create under a label another row holds, and
    # an active row may serve the user elsewhere; refuse before any write and before the key
    # leaves. Disconnecting `E` makes that row the effective one.
    effective = row(
        provider="anthropic", auth_type="oauth", status="error", label="work", effective=True
    )
    holder = row(OTHER_ID, provider="anthropic")
    gateway = Gateway(effective, holder, providers=(BOTH,))
    adapter = gateway.adapter()

    with pytest.raises(ConnectionConflict):
        if operation == "connect":
            await adapter.connect(Caller(), "anthropic", SECRET)
        else:
            await adapter.start_oauth(Caller(), "anthropic")

    assert gateway.writes() == []
    assert all(SECRET not in request.content.decode() for request in gateway.requests)


async def test_connect_refuses_an_active_effective_oauth_row_before_sending_the_key() -> None:
    gateway = Gateway(
        row(provider="anthropic", auth_type="oauth", label="work", effective=True),
        providers=(BOTH,),
    )

    with pytest.raises(ConnectionAlreadyConnected):
        await gateway.adapter().connect(Caller(), "anthropic", SECRET)

    assert gateway.writes() == []
    assert all(SECRET not in request.content.decode() for request in gateway.requests)


@pytest.mark.parametrize("operation", ["connect", "start_oauth"])
async def test_a_pending_effective_row_is_a_conflict(operation: str) -> None:
    pending = row(provider="anthropic", auth_type="oauth", status="pending", effective=True)
    gateway = Gateway(pending, providers=(BOTH,))
    adapter = gateway.adapter()

    with pytest.raises(ConnectionConflict):
        if operation == "connect":
            await adapter.connect(Caller(), "anthropic", SECRET)
        else:
            await adapter.start_oauth(Caller(), "anthropic")

    assert gateway.writes() == []


@pytest.mark.parametrize("operation", ["connect", "start_oauth", "disconnect"])
async def test_two_active_rows_with_none_effective_are_a_conflict(operation: str) -> None:
    gateway = Gateway(
        row(provider="anthropic", label="one"),
        row(OTHER_ID, provider="anthropic", auth_type="oauth", label="two"),
        providers=(BOTH,),
    )
    adapter = gateway.adapter()

    with pytest.raises(ConnectionConflict):
        if operation == "connect":
            await adapter.connect(Caller(), "anthropic", SECRET)
        elif operation == "start_oauth":
            await adapter.start_oauth(Caller(), "anthropic")
        else:
            await adapter.disconnect(Caller(), "anthropic")

    assert gateway.writes() == []


async def test_connect_rekeys_a_screamingface_error_row_when_nothing_is_effective() -> None:
    # INVARIANT (spec §3, accepted limitation): the label is the only mark of an Engine row, so a
    # row the user named `screamingface` outside the Engine, in `error`, is re-keyed in place and
    # turns `active` with the key the Engine was given. It served nothing either way.
    users_row = row(status="error")
    gateway = Gateway(users_row, access_after_write={"openrouter": "connected"})

    connection = await gateway.adapter().connect(Caller(), "openrouter", SECRET)

    assert gateway.writes() == [f"PUT {ROWS_PATH}/{E_ID}/api-key"]
    assert connection.status == "connected"


async def test_connect_removes_its_stale_rows_then_creates_and_leaves_the_users_rows() -> None:
    abandoned_start = row(provider="anthropic", auth_type="oauth", status="pending")
    users_error = row(OTHER_ID, provider="anthropic", status="error", label="research")
    users_pending = row(
        THIRD_ID, provider="anthropic", auth_type="oauth", status="pending", label="work"
    )
    gateway = Gateway(
        abandoned_start,
        users_error,
        users_pending,
        providers=(BOTH,),
        access_after_write={"anthropic": "connected"},
    )

    await gateway.adapter().connect(Caller(), "anthropic", SECRET)

    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{E_ID}", f"POST {ROWS_PATH}/api-key"]
    assert gateway.bodies() == [
        {"provider": "anthropic", "label": "screamingface", "api_key": SECRET}
    ]


async def test_connect_with_nothing_to_repair_only_creates() -> None:
    gateway = Gateway(access_after_write={"openrouter": "connected"})

    connection = await gateway.adapter().connect(Caller(), "openrouter", SECRET)

    assert gateway.writes() == [f"POST {ROWS_PATH}/api-key"]
    assert connection.status == "connected"


@pytest.mark.parametrize("listed", ["needs_reauth", "error"])
async def test_connect_returns_the_status_listed_after_its_write(listed: ConnectionStatus) -> None:
    gateway = Gateway(access={}, access_after_write={"openrouter": listed})

    connection = await gateway.adapter().connect(Caller(), "openrouter", SECRET)

    # INVARIANT (spec §3): never a status derived from the written row (it is `active`).
    assert connection == Connection(
        "openrouter", "OpenRouter", ("api_key",), listed, auth_method="api_key"
    )
    assert gateway.calls()[-2:] == [f"POST {ROWS_PATH}/api-key", f"GET {ACCESS_PATH}"]


async def test_a_written_row_of_another_provider_is_a_bad_response() -> None:
    # INVARIANT (spec §3, response checks): the written row must be the requested provider's.
    gateway = Gateway(access_after_write={"openrouter": "connected"})
    gateway.fail[f"POST {ROWS_PATH}/api-key"] = httpx.Response(
        201, json=written(row(CREATED_ID, provider="anthropic"))
    )

    with pytest.raises(ConnectionBadResponse):
        await gateway.adapter().connect(Caller(), "openrouter", SECRET)


async def test_a_label_conflict_on_create_is_a_conflict() -> None:
    gateway = Gateway()
    gateway.fail[f"POST {ROWS_PATH}/api-key"] = httpx.Response(
        409, json={"detail": {"code": "label_conflict", "label": "screamingface"}}
    )

    with pytest.raises(ConnectionConflict):
        await gateway.adapter().connect(Caller(), "openrouter", SECRET)


# --- start_oauth -------------------------------------------------------------------------------


@pytest.mark.parametrize("auth_type", ["api_key", "oauth"])
async def test_start_oauth_refuses_an_active_effective_row(auth_type: str) -> None:
    gateway = Gateway(
        row(provider="anthropic", auth_type=auth_type, label="work", effective=True),
        providers=(BOTH,),
    )

    with pytest.raises(ConnectionAlreadyConnected):
        await gateway.adapter().start_oauth(Caller(), "anthropic")

    assert gateway.writes() == []


@pytest.mark.parametrize(
    ("auth_type", "status"), [("api_key", "error"), ("oauth", "expired"), ("oauth", "revoked")]
)
async def test_start_oauth_replaces_an_unusable_effective_row(auth_type: str, status: str) -> None:
    effective = row(provider="anthropic", auth_type=auth_type, status=status, effective=True)
    gateway = Gateway(effective, providers=(BOTH,))

    await gateway.adapter().start_oauth(Caller(), "anthropic")

    # WHY the effective row stays: the callback replaces it, even when it holds the label.
    assert gateway.writes() == [f"POST {ROWS_PATH}"]
    assert gateway.bodies() == [{"provider": "anthropic", "label": "screamingface"}]


async def test_start_oauth_removes_an_error_row_labelled_screamingface_then_starts() -> None:
    # INVARIANT (spec §3, accepted limitation): with nothing effective, an `error` API-key row
    # labelled `screamingface` — the Engine's or the user's — is removed by the repair here.
    stale = row(provider="anthropic", status="error")
    users_pending = row(
        OTHER_ID, provider="anthropic", auth_type="oauth", status="pending", label="work"
    )
    gateway = Gateway(stale, users_pending, providers=(BOTH,))

    await gateway.adapter().start_oauth(Caller(), "anthropic")

    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{E_ID}", f"POST {ROWS_PATH}"]


# --- disconnect --------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["active", "error", "pending", "expired"])
async def test_disconnect_deletes_the_effective_row_whatever_its_label_and_status(
    status: str,
) -> None:
    gateway = Gateway(
        row(status=status, label="research", effective=True),
        access={"openrouter": "connected"},
        access_after_write={"openrouter": "not_connected"},
    )

    connection = await gateway.adapter().disconnect(Caller(), "openrouter")

    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{E_ID}"]
    assert connection == Connection("openrouter", "OpenRouter", ("api_key",), "not_connected")
    assert gateway.calls()[-1] == f"GET {ACCESS_PATH}"


async def test_disconnect_with_an_effective_row_deletes_only_that_row() -> None:
    # WHY (spec §3 table): with `E` present, `disconnect` is `DELETE E`; the stale-row repair is
    # the no-`E` path only.
    stale = row(OTHER_ID, provider="anthropic", auth_type="oauth", status="pending")
    effective = row(provider="anthropic", status="error", label="research", effective=True)
    gateway = Gateway(effective, stale, providers=(BOTH,), access={"anthropic": "error"})

    await gateway.adapter().disconnect(Caller(), "anthropic")

    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{E_ID}"]


async def test_disconnect_with_a_second_active_row_returns_connected() -> None:
    # WHY (spec §3): deleting E clears the pair's reference; the other active row becomes
    # effective and chat goes on using it, so the provider stays `connected`.
    gateway = Gateway(
        row(effective=True),
        row(OTHER_ID, label="research"),
        access={"openrouter": "connected"},
        access_after_write={"openrouter": "connected"},
    )

    connection = await gateway.adapter().disconnect(Caller(), "openrouter")

    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{E_ID}"]
    assert connection.status == "connected"


async def test_disconnect_without_an_effective_row_only_repairs() -> None:
    stale = row(provider="anthropic", auth_type="oauth", status="pending")
    users_error = row(OTHER_ID, provider="anthropic", status="error", label="research")
    gateway = Gateway(stale, users_error, providers=(BOTH,), access={"anthropic": "error"})

    connection = await gateway.adapter().disconnect(Caller(), "anthropic")

    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{E_ID}"]
    assert connection.status == "error"


async def test_disconnect_with_nothing_to_remove_is_idempotent() -> None:
    gateway = Gateway(access={})
    adapter = gateway.adapter()

    first = await adapter.disconnect(Caller(), "openrouter")
    second = await adapter.disconnect(Caller(), "openrouter")

    assert first == second == Connection("openrouter", "OpenRouter", ("api_key",), "not_connected")
    assert gateway.writes() == []


async def test_disconnect_tolerates_a_concurrent_delete_and_reports_the_listed_status() -> None:
    gateway = Gateway(row(effective=True), access={"openrouter": "not_connected"})
    gateway.fail[f"DELETE {ROWS_PATH}/{E_ID}"] = httpx.Response(
        404, json={"detail": {"code": "connection_not_found"}}
    )

    connection = await gateway.adapter().disconnect(Caller(), "openrouter")

    assert connection.status == "not_connected"
    assert gateway.calls()[-1] == f"GET {ACCESS_PATH}"
