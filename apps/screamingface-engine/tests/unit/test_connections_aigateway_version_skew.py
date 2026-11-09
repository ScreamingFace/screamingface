"""A Local Engine against a gateway older than L7a (OME-1138 close-out, L7b, Q3 option A).

FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §4 — when no listed row
carries `effective`, the Engine selects by the label rule for one Engine release and logs once per
process that the gateway predates the field. The status still comes from `/v1/provider-access`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx
import pytest

from screamingface_engine.connections import aigateway_rows
from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import Caller, Connection, ConnectionConflict

pytestmark = pytest.mark.asyncio

MANAGED_ID = "00000000-0000-0000-0000-000000000001"
USERS_ID = "00000000-0000-0000-0000-000000000002"
CREATED_ID = "00000000-0000-0000-0000-0000000000c0"
ROWS_PATH = "/v1/oauth/connections"
ACCESS_PATH = "/v1/provider-access"
SKEW_LOGGER = "screamingface_engine.connections.aigateway_rows"


@pytest.fixture(autouse=True)
def _a_fresh_process() -> Iterator[None]:
    # WHY: the notice is once per process; each test starts as a fresh process would.
    aigateway_rows._note_gateway_predates_effective.cache_clear()  # noqa: SLF001
    yield
    aigateway_rows._note_gateway_predates_effective.cache_clear()  # noqa: SLF001


def _row(connection_id: str, label: str) -> dict[str, object]:
    """A row as a gateway older than L7a lists it: no `effective` field."""
    return {
        "id": connection_id,
        "provider": "openrouter",
        "label": label,
        "status": "active",
        "auth_type": "api_key",
        "account": None,
    }


def _adapter(
    rows: list[dict[str, object]],
    access: dict[str, str],
    seen: list[str],
    *,
    auth_methods: tuple[str, ...] = ("api_key",),
) -> AigatewayConnections:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path == "/v1/providers":
            provider = {
                "object": "provider",
                "id": "openrouter",
                "display_name": "OpenRouter",
                "auth_methods": list(auth_methods),
            }
            return httpx.Response(200, json={"object": "list", "data": [provider]})
        if request.url.path == ACCESS_PATH:
            listed = [{"provider": key, "status": value} for key, value in access.items()]
            return httpx.Response(200, json={"providers": listed})
        if request.method == "GET":
            return httpx.Response(200, json={"connections": rows})
        if request.method == "PUT":
            (row,) = [row for row in rows if f"/{row['id']}/" in request.url.path]
            return httpx.Response(200, json=row)
        body = json.loads(request.content)
        return httpx.Response(201, json=_row(CREATED_ID, body["label"]))

    client = httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(handler)
    )
    return AigatewayConnections(client)


def _skew_notices(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == SKEW_LOGGER]


async def test_a_listing_without_the_field_selects_by_label_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rows = [_row(USERS_ID, "research"), _row(MANAGED_ID, "screamingface")]
    adapter = _adapter(rows, {"openrouter": "needs_reauth"}, [])
    caplog.set_level(logging.INFO, logger=SKEW_LOGGER)

    first = await adapter.list(Caller())
    second = await adapter.list(Caller())

    # WHY the status is still the gateway's: `/v1/provider-access` predates L7a (A4).
    expected = Connection(
        "openrouter", "OpenRouter", ("api_key",), "needs_reauth", auth_method="api_key"
    )
    assert first == second == (expected,)
    (notice,) = _skew_notices(caplog)
    assert notice.levelno == logging.WARNING
    assert "effective" in notice.getMessage()


async def test_a_listing_with_zero_rows_reads_the_same_under_both_rules(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[str] = []
    adapter = _adapter([], {"openrouter": "not_connected"}, seen)
    caplog.set_level(logging.INFO, logger=SKEW_LOGGER)

    assert await adapter.list(Caller()) == (
        Connection("openrouter", "OpenRouter", ("api_key",), "not_connected"),
    )
    # WHY no notice: an empty listing cannot tell an older gateway from a current one.
    assert _skew_notices(caplog) == []
    assert seen[-1] == f"GET {ACCESS_PATH}"


async def test_writes_follow_the_label_row_under_the_fallback() -> None:
    seen: list[str] = []
    rows = [_row(USERS_ID, "research"), _row(MANAGED_ID, "screamingface")]
    adapter = _adapter(rows, {"openrouter": "connected"}, seen)

    connection = await adapter.connect(Caller(), "openrouter", "sk-or-v1-unit-secret")

    assert [call for call in seen if not call.startswith("GET ")] == [
        f"PUT {ROWS_PATH}/{MANAGED_ID}/api-key"
    ]
    assert connection.status == "connected"
    assert seen[-1] == f"GET {ACCESS_PATH}"


async def test_without_a_label_row_the_fallback_creates_beside_one_user_row() -> None:
    # WHY (today's label rule, kept for one release): an older gateway cannot say which row chat
    # serves, so the Engine creates its own row as it did before L7b.
    seen: list[str] = []
    adapter = _adapter([_row(USERS_ID, "research")], {"openrouter": "connected"}, seen)

    await adapter.connect(Caller(), "openrouter", "sk-or-v1-unit-secret")

    assert [call for call in seen if not call.startswith("GET ")] == [f"POST {ROWS_PATH}/api-key"]


@pytest.mark.parametrize("operation", ["connect", "start_oauth", "disconnect"])
async def test_without_a_label_row_two_active_user_rows_are_a_conflict(operation: str) -> None:
    # WHY (owner, 2026-11-04): under the fallback the label row stands in for `E`, so without one
    # and with two or more active rows the table's "no `E`, `A` >= 2" applies: refuse before any
    # write. Before L7b, `connect` created a third row and `disconnect` reported `not_connected`.
    seen: list[str] = []
    rows = [_row(USERS_ID, "research"), _row(CREATED_ID, "work")]
    adapter = _adapter(rows, {"openrouter": "connected"}, seen, auth_methods=("api_key", "oauth"))
    secret = "sk-or-v1-unit-secret"

    with pytest.raises(ConnectionConflict):
        if operation == "connect":
            await adapter.connect(Caller(), "openrouter", secret)
        elif operation == "start_oauth":
            await adapter.start_oauth(Caller(), "openrouter")
        else:
            await adapter.disconnect(Caller(), "openrouter")

    assert [call for call in seen if not call.startswith("GET ")] == []
