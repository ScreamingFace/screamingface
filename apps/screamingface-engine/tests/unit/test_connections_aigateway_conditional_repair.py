"""The Local Engine's stale-row repair removes a row only while it is still stale (OME-1138, L7b).

FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2a and §3 — every repair
`DELETE` carries `expected_status`, the status the listing showed, and the gateway refuses (409)
a row that started serving since. Only `disconnect` of `E`, the user's explicit intent, deletes
plainly.
INVARIANT: a refused repair is `ConnectionConflict`, raised before any create or start, so the key
never leaves the Engine and the row the user just finished stays.
STORY: as a Local Engine user, a sign-in or key fix I finish while the Engine repairs its rows is
never deleted by that repair.
"""

from __future__ import annotations

import httpx
import pytest
from aigateway_effective_support import (
    BOTH,
    E_ID,
    OTHER_ID,
    ROWS_PATH,
    SECRET,
    THIRD_ID,
    Gateway,
    row,
)

from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import Caller, ConnectionConflict

pytestmark = pytest.mark.asyncio


async def _run(adapter: AigatewayConnections, operation: str) -> object:
    if operation == "connect":
        return await adapter.connect(Caller(), "anthropic", SECRET)
    if operation == "start_oauth":
        return await adapter.start_oauth(Caller(), "anthropic")
    return await adapter.disconnect(Caller(), "anthropic")


def _deletes(gateway: Gateway) -> list[httpx.Request]:
    return [request for request in gateway.requests if request.method == "DELETE"]


def _assert_refused_before_any_write(gateway: Gateway) -> None:
    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{THIRD_ID}"]
    assert all(SECRET.encode() not in request.content for request in gateway.requests)
    (kept,) = [listed for listed in gateway.rows if listed["id"] == THIRD_ID]
    assert kept["status"] == "active"


# --- a row that started serving since the listing stops the repair -----------------------------


@pytest.mark.parametrize("operation", ["connect", "start_oauth", "disconnect"])
async def test_a_sign_in_finished_since_the_listing_stops_the_repair(operation: str) -> None:
    abandoned_start = row(THIRD_ID, provider="anthropic", auth_type="oauth", status="pending")
    gateway = Gateway(abandoned_start, providers=(BOTH,))
    gateway.activate_at_delete.add(THIRD_ID)

    with pytest.raises(ConnectionConflict):
        await _run(gateway.adapter(), operation)

    _assert_refused_before_any_write(gateway)


@pytest.mark.parametrize("operation", ["connect", "start_oauth"])
async def test_a_sign_in_finished_since_the_listing_stops_the_repair_beside_an_unusable_e(
    operation: str,
) -> None:
    unusable = row(
        OTHER_ID,
        provider="anthropic",
        auth_type="oauth",
        status="error",
        label="work",
        effective=True,
    )
    abandoned_start = row(THIRD_ID, provider="anthropic", auth_type="oauth", status="pending")
    gateway = Gateway(unusable, abandoned_start, providers=(BOTH,))
    gateway.activate_at_delete.add(THIRD_ID)

    with pytest.raises(ConnectionConflict):
        await _run(gateway.adapter(), operation)

    _assert_refused_before_any_write(gateway)


@pytest.mark.parametrize("operation", ["start_oauth", "disconnect"])
async def test_a_key_fixed_since_the_listing_stops_the_repair(operation: str) -> None:
    # WHY not `connect`: with nothing effective it re-keys its own `error` row in place (`PUT`).
    broken_key = row(THIRD_ID, provider="anthropic", status="error")
    gateway = Gateway(broken_key, providers=(BOTH,))
    gateway.activate_at_delete.add(THIRD_ID)

    with pytest.raises(ConnectionConflict):
        await _run(gateway.adapter(), operation)

    _assert_refused_before_any_write(gateway)


# --- what each DELETE requires ------------------------------------------------------------------


@pytest.mark.parametrize(("auth_type", "status"), [("oauth", "pending"), ("api_key", "error")])
async def test_a_repair_delete_requires_the_status_the_listing_showed(
    auth_type: str, status: str
) -> None:
    stale = row(THIRD_ID, provider="anthropic", auth_type=auth_type, status=status)
    gateway = Gateway(stale, providers=(BOTH,))

    await gateway.adapter().start_oauth(Caller(), "anthropic")

    (deleted,) = _deletes(gateway)
    assert dict(deleted.url.params) == {"expected_status": status}
    assert gateway.writes() == [f"DELETE {ROWS_PATH}/{THIRD_ID}", f"POST {ROWS_PATH}"]


@pytest.mark.parametrize("status", ["active", "error", "pending"])
async def test_disconnect_deletes_the_effective_row_without_a_condition(status: str) -> None:
    gateway = Gateway(
        row(status=status, label="research", effective=True),
        access_after_write={"openrouter": "not_connected"},
    )

    await gateway.adapter().disconnect(Caller(), "openrouter")

    (deleted,) = _deletes(gateway)
    assert deleted.url.path == f"{ROWS_PATH}/{E_ID}"
    assert dict(deleted.url.params) == {}


async def test_a_labelled_row_in_a_status_the_gateway_cannot_require_is_never_deleted() -> None:
    # WHY: the conditional delete takes only `pending` and `error` (spec §2a). Nothing writes
    # `expired` today and a `revoked` row never keeps the label, so such a row is left to the
    # create's 409 `label_conflict` rather than deleted without a condition.
    stuck = row(THIRD_ID, provider="anthropic", auth_type="oauth", status="expired")
    gateway = Gateway(stuck, providers=(BOTH,))
    gateway.fail[f"POST {ROWS_PATH}"] = httpx.Response(
        409, json={"detail": {"code": "label_conflict", "label": "screamingface"}}
    )

    with pytest.raises(ConnectionConflict):
        await gateway.adapter().start_oauth(Caller(), "anthropic")

    assert gateway.writes() == [f"POST {ROWS_PATH}"]
